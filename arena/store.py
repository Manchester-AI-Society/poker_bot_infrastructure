"""SQLite-backed state for the competition.

One file (``<root>/arena.sqlite``) holds submissions, the job queue and
results. SQLite in WAL mode lets several worker processes read and write
safely, on a laptop or on an HPC node with a local disk. No server is
needed.

Layout under ``root``::

    arena.sqlite          state
    versions/<team>/<h>/  immutable copy of each submitted bot version
    hands/<job>.jsonl.gz  full hand histories of each pairing
    logs/<team>/...       team-private bot logs
    results/*.json        leaderboard snapshots for the frontend
"""

from __future__ import annotations

import json
import math
import secrets
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Sequence

from .procs import pid_alive, worker_pid
from .stats import ci95, pool

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS versions (
    hash TEXT PRIMARY KEY, team TEXT NOT NULL, path TEXT NOT NULL,
    status TEXT NOT NULL, message TEXT, created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS current (
    team TEXT PRIMARY KEY, hash TEXT NOT NULL REFERENCES versions(hash));
CREATE TABLE IF NOT EXISTS freezes (
    id INTEGER PRIMARY KEY AUTOINCREMENT, created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS freeze_members (
    freeze_id INTEGER NOT NULL REFERENCES freezes(id),
    team TEXT NOT NULL, hash TEXT NOT NULL,
    PRIMARY KEY (freeze_id, team));
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL, freeze_id INTEGER,
    a_hash TEXT NOT NULL, b_hash TEXT NOT NULL,
    deals INTEGER NOT NULL, seed INTEGER NOT NULL,
    status TEXT NOT NULL, worker TEXT, error TEXT,
    created_at REAL NOT NULL, started_at REAL, finished_at REAL,
    round INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS results (
    job_id INTEGER PRIMARY KEY REFERENCES jobs(id),
    data TEXT NOT NULL, hands_path TEXT);
"""


@dataclass(frozen=True)
class Version:
    hash: str
    team: str
    path: str
    status: str
    message: Optional[str]
    created_at: float


@dataclass(frozen=True)
class Job:
    id: int
    kind: str
    freeze_id: Optional[int]
    a_hash: str
    b_hash: str
    deals: int
    seed: int


class Store:
    def __init__(self, root: Path | str):
        self.root = Path(root)
        for sub in ("versions", "hands", "logs", "results"):
            (self.root / sub).mkdir(parents=True, exist_ok=True)
        self.db_path = self.root / "arena.sqlite"
        with self._conn() as conn:
            conn.executescript(SCHEMA)
            self._migrate(conn)
            conn.execute(
                "INSERT OR IGNORE INTO meta(key, value) VALUES (?, ?)",
                ("seed", str(secrets.randbits(48))),
            )

    @staticmethod
    def _migrate(conn: sqlite3.Connection) -> None:
        """Brings a database made by an older version up to date.

        A pairing used to be unique per (kind, freeze, a, b). With timed
        cycles the same pairing is played again every round, so the round is
        part of the key; every older job is round 0.
        """
        columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(jobs)")
        }
        if "round" not in columns:
            conn.execute(
                "ALTER TABLE jobs ADD COLUMN round INTEGER NOT NULL DEFAULT 0"
            )
            conn.execute("DROP INDEX IF EXISTS jobs_pair")
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS jobs_pair_round "
            "ON jobs(kind, IFNULL(freeze_id, 0), round, a_hash, b_hash) "
            "WHERE status != 'stale'"
        )

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path, timeout=60, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=60000")
        try:
            yield conn
        finally:
            conn.close()

    # -- meta -----------------------------------------------------------

    @property
    def base_seed(self) -> int:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT value FROM meta WHERE key='seed'"
            ).fetchone()
        return int(row["value"])

    def set_sync_status(self, team: str, status: str, message: str) -> None:
        """Remembers the outcome of the latest attempt to fetch ``team``.

        ``at`` is when the outcome last CHANGED; ``checked_at`` is when it was
        last looked at. Only ``at`` is published. If the published time moved
        on every pass (a pass runs every minute), the website data would change
        every minute, and a git host would deploy it every minute for nothing.
        """
        now = time.time()
        key = f"sync:{team}"
        with self._conn() as conn:
            row = conn.execute(
                "SELECT value FROM meta WHERE key=?", (key,)
            ).fetchone()
            previous = json.loads(row["value"]) if row else {}
            same = (
                previous.get("status") == status
                and previous.get("message") == message
            )
            value = json.dumps(
                {
                    "status": status,
                    "message": message,
                    "at": previous.get("at", now) if same else now,
                    "checked_at": now,
                }
            )
            conn.execute(
                "INSERT INTO meta(key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )

    def sync_statuses(self) -> Dict[str, Dict[str, Any]]:
        """Latest fetch outcome per team: status, message and time."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT key, value FROM meta WHERE key LIKE 'sync:%'"
            ).fetchall()
        return {
            row["key"].removeprefix("sync:"): json.loads(row["value"])
            for row in rows
        }

    # -- registrations (teams that signed up through the registry) -----

    def team_claim(self, team: str) -> Optional[Dict[str, Any]]:
        """Who first had ``team`` accepted, or None. Names stay claimed."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT value FROM meta WHERE key=?", (f"claim:{team}",)
            ).fetchone()
        return json.loads(row["value"]) if row else None

    def claim_team(self, team: str, user: str, issue: int) -> bool:
        """Claims a team name for an account; the first claim wins."""
        value = json.dumps({"user": user, "issue": issue, "at": time.time()})
        with self._conn() as conn:
            cursor = conn.execute(
                "INSERT OR IGNORE INTO meta(key, value) VALUES (?, ?)",
                (f"claim:{team}", value),
            )
        return cursor.rowcount == 1

    def set_registration(self, issue: int, record: Dict[str, Any]) -> None:
        """Saves the latest decision for a registration issue.

        The marker for which outcome was already commented on is kept, so a
        registrant is not told the same thing every pass.
        """
        key = f"reg:{issue}"
        with self._conn() as conn:
            row = conn.execute(
                "SELECT value FROM meta WHERE key=?", (key,)
            ).fetchone()
            previous = json.loads(row["value"]) if row else {}
            merged = {**record, "feedback": previous.get("feedback")}
            if previous and all(
                previous.get(k) == merged.get(k) for k in merged
            ):
                return  # nothing changed: leave the stored time alone
            merged["at"] = time.time()
            conn.execute(
                "INSERT INTO meta(key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, json.dumps(merged)),
            )

    def set_registration_feedback(self, issue: int, marker: str) -> None:
        key = f"reg:{issue}"
        with self._conn() as conn:
            row = conn.execute(
                "SELECT value FROM meta WHERE key=?", (key,)
            ).fetchone()
            if row is None:
                return
            record = json.loads(row["value"])
            record["feedback"] = marker
            conn.execute(
                "UPDATE meta SET value=? WHERE key=?",
                (json.dumps(record), key),
            )

    def registrations(self) -> Dict[int, Dict[str, Any]]:
        """Latest decision per registration issue number."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT key, value FROM meta WHERE key LIKE 'reg:%'"
            ).fetchall()
        return {
            int(row["key"].removeprefix("reg:")): json.loads(row["value"])
            for row in rows
        }

    def drop_registrations_except(self, issues: set) -> None:
        """Forgets registrations whose issue is gone or closed (withdrawn)."""
        for number in list(self.registrations()):
            if number not in issues:
                with self._conn() as conn:
                    conn.execute(
                        "DELETE FROM meta WHERE key=?", (f"reg:{number}",)
                    )

    # -- versions -------------------------------------------------------

    def add_version(
        self, team: str, digest: str, path: str, status: str, message: str
    ) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO versions VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(hash) DO UPDATE SET status=excluded.status, "
                "message=excluded.message",
                (digest, team, path, status, message, time.time()),
            )

    def get_version(self, digest: str) -> Optional[Version]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM versions WHERE hash=?", (digest,)
            ).fetchone()
        return Version(**dict(row)) if row else None

    def set_current(self, team: str, digest: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO current(team, hash) VALUES (?, ?) "
                "ON CONFLICT(team) DO UPDATE SET hash=excluded.hash",
                (team, digest),
            )

    def current_versions(self) -> List[Version]:
        """Each team's current valid version, ordered by team."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT v.* FROM current c JOIN versions v ON v.hash=c.hash "
                "WHERE v.status='valid' ORDER BY v.team"
            ).fetchall()
        return [Version(**dict(row)) for row in rows]

    def versions_of(self, team: str) -> List[Version]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM versions WHERE team=? ORDER BY created_at",
                (team,),
            ).fetchall()
        return [Version(**dict(row)) for row in rows]

    def all_versions(self) -> List[Version]:
        """Every submitted version, valid or not, oldest first."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM versions ORDER BY created_at, hash"
            ).fetchall()
        return [Version(**dict(row)) for row in rows]

    def unset_current(self, team: str) -> None:
        """Takes a team out of play (its versions are kept)."""
        with self._conn() as conn:
            conn.execute("DELETE FROM current WHERE team=?", (team,))

    def current_hash(self, team: str) -> Optional[str]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT hash FROM current WHERE team=?", (team,)
            ).fetchone()
        return row["hash"] if row else None

    # -- freezes --------------------------------------------------------

    def create_freeze(self, members: Sequence[Version]) -> int:
        with self._conn() as conn:
            cursor = conn.execute(
                "INSERT INTO freezes(created_at) VALUES (?)", (time.time(),)
            )
            freeze_id = int(cursor.lastrowid)
            conn.executemany(
                "INSERT INTO freeze_members VALUES (?, ?, ?)",
                [(freeze_id, v.team, v.hash) for v in members],
            )
        return freeze_id

    def latest_freeze(self) -> Optional[int]:
        with self._conn() as conn:
            row = conn.execute("SELECT MAX(id) AS id FROM freezes").fetchone()
        return row["id"]

    def freeze_members(self, freeze_id: int) -> List[Version]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT v.* FROM freeze_members m "
                "JOIN versions v ON v.hash=m.hash "
                "WHERE m.freeze_id=? ORDER BY m.team",
                (freeze_id,),
            ).fetchall()
        return [Version(**dict(row)) for row in rows]

    # -- jobs -----------------------------------------------------------

    def create_job(
        self,
        kind: str,
        a_hash: str,
        b_hash: str,
        deals: int,
        seed: int,
        freeze_id: Optional[int] = None,
        round: int = 0,
    ) -> Optional[int]:
        """Queues a pairing; returns None if it already exists this round."""
        a_hash, b_hash = sorted((a_hash, b_hash))
        with self._conn() as conn:
            try:
                cursor = conn.execute(
                    "INSERT INTO jobs(kind, freeze_id, a_hash, b_hash, "
                    "deals, seed, status, created_at, round) "
                    "VALUES (?, ?, ?, ?, ?, ?, 'queued', ?, ?)",
                    (
                        kind,
                        freeze_id,
                        a_hash,
                        b_hash,
                        deals,
                        seed,
                        time.time(),
                        round,
                    ),
                )
            except sqlite3.IntegrityError:
                return None
        return int(cursor.lastrowid)

    def claim_job(
        self, worker: str, kinds: Sequence[str] = ("ladder", "final")
    ) -> Optional[Job]:
        """Atomically takes the newest queued job.

        Ladder jobs whose bots are no longer current are discarded as
        stale instead of being run.
        """
        marks = ",".join("?" for _ in kinds)
        with self._conn() as conn:
            while True:
                conn.execute("BEGIN IMMEDIATE")
                row = conn.execute(
                    "SELECT * FROM jobs WHERE status='queued' "
                    f"AND kind IN ({marks}) ORDER BY id DESC LIMIT 1",
                    tuple(kinds),
                ).fetchone()
                if row is None:
                    conn.execute("COMMIT")
                    return None
                if row["kind"] == "ladder" and not self._both_current(
                    conn, row["a_hash"], row["b_hash"]
                ):
                    conn.execute(
                        "UPDATE jobs SET status='stale', finished_at=? "
                        "WHERE id=?",
                        (time.time(), row["id"]),
                    )
                    conn.execute("COMMIT")
                    continue
                conn.execute(
                    "UPDATE jobs SET status='running', worker=?, "
                    "started_at=? WHERE id=?",
                    (worker, time.time(), row["id"]),
                )
                conn.execute("COMMIT")
                return Job(
                    id=row["id"],
                    kind=row["kind"],
                    freeze_id=row["freeze_id"],
                    a_hash=row["a_hash"],
                    b_hash=row["b_hash"],
                    deals=row["deals"],
                    seed=row["seed"],
                )

    @staticmethod
    def _both_current(conn, a_hash: str, b_hash: str) -> bool:
        count = conn.execute(
            "SELECT COUNT(*) AS n FROM current WHERE hash IN (?, ?)",
            (a_hash, b_hash),
        ).fetchone()["n"]
        return count == 2

    def get_job(self, job_id: int) -> Job:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM jobs WHERE id=?", (job_id,)
            ).fetchone()
        return Job(
            id=row["id"],
            kind=row["kind"],
            freeze_id=row["freeze_id"],
            a_hash=row["a_hash"],
            b_hash=row["b_hash"],
            deals=row["deals"],
            seed=row["seed"],
        )

    def finish_job(
        self, job_id: int, data: Dict[str, Any], hands_path: Optional[str]
    ) -> None:
        with self._conn() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "INSERT OR REPLACE INTO results(job_id, data, hands_path) "
                "VALUES (?, ?, ?)",
                (job_id, json.dumps(data), hands_path),
            )
            conn.execute(
                "UPDATE jobs SET status='done', finished_at=? WHERE id=?",
                (time.time(), job_id),
            )
            conn.execute("COMMIT")

    def fail_job(self, job_id: int, error: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE jobs SET status='failed', error=?, finished_at=? "
                "WHERE id=?",
                (error[-2000:], time.time(), job_id),
            )

    def requeue_running(self) -> int:
        """Puts jobs left 'running' by a DEAD scheduler back in the queue.

        A job whose scheduler is still alive is left alone. Two schedulers can
        share one results folder (a ladder and a final, say); taking the other
        one's running job would run the same pairing twice at once, and both
        runs would write the same hand-history file.
        """
        released = 0
        with self._conn() as conn:
            running = conn.execute(
                "SELECT id, worker FROM jobs WHERE status='running'"
            ).fetchall()
            for row in running:
                pid = worker_pid(row["worker"])
                if pid is not None and pid_alive(pid):
                    continue
                cursor = conn.execute(
                    "UPDATE jobs SET status='queued', worker=NULL "
                    "WHERE id=? AND status='running' AND worker IS ?",
                    (row["id"], row["worker"]),
                )
                released += cursor.rowcount
        return released

    def requeue_failed(self) -> int:
        """Drops failed jobs so their pairings can be queued again."""
        with self._conn() as conn:
            cursor = conn.execute("DELETE FROM jobs WHERE status='failed'")
        return cursor.rowcount

    def job_counts(self, kind: Optional[str] = None) -> Dict[str, int]:
        query = "SELECT status, COUNT(*) AS n FROM jobs"
        params: tuple = ()
        if kind:
            query += " WHERE kind=?"
            params = (kind,)
        query += " GROUP BY status"
        with self._conn() as conn:
            rows = conn.execute(query, params).fetchall()
        return {row["status"]: row["n"] for row in rows}

    # -- the tournament -----------------------------------------------

    def tournament(self) -> Optional[Dict[str, Any]]:
        value = self.meta_get("tournament")
        return None if value is None else json.loads(value)

    def set_tournament(self, state: Dict[str, Any]) -> None:
        self.meta_set("tournament", json.dumps(state))

    def jobs_of(
        self, kind: str, freeze_id: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """Every job of a kind (and freeze), oldest first."""
        query = (
            "SELECT id, a_hash, b_hash, status, freeze_id FROM jobs "
            "WHERE kind=? AND status != 'stale'"
        )
        params: List[Any] = [kind]
        if freeze_id is not None:
            query += " AND freeze_id=?"
            params.append(freeze_id)
        with self._conn() as conn:
            rows = conn.execute(query + " ORDER BY id", params).fetchall()
        return [dict(row) for row in rows]

    def claim_job_by_id(self, job_id: int, worker: str) -> bool:
        """Takes one specific queued job; False if someone else has it."""
        with self._conn() as conn:
            cursor = conn.execute(
                "UPDATE jobs SET status='running', worker=?, started_at=? "
                "WHERE id=? AND status='queued'",
                (worker, time.time(), job_id),
            )
            return cursor.rowcount == 1

    # -- timed cycles ---------------------------------------------------

    def meta_get(self, key: str) -> Optional[str]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT value FROM meta WHERE key=?", (key,)
            ).fetchone()
        return None if row is None else row["value"]

    def meta_set(self, key: str, value: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO meta(key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )

    def cycle_done(self) -> Optional[int]:
        """The last ladder round that finished, or None if not cycling.

        Results of a round still being played are hidden, so that what is
        published is always whole rounds (one cycle, one consistent table).
        """
        value = self.meta_get("ladder_round_done")
        return None if value is None else int(value)

    def finish_round(self, round: int) -> None:
        self.meta_set("ladder_round_done", str(round))

    def last_round(self, kind: str = "ladder") -> int:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT MAX(round) AS r FROM jobs WHERE kind=?", (kind,)
            ).fetchone()
        return int(row["r"] or 0)

    def prune_old_hands(self, kind: str = "ladder") -> int:
        """Deletes hand files that a newer round of the same pairing replaced.

        Only the newest round's hands are ever shown, and a cycle every few
        minutes would otherwise keep every round of every pairing for the
        whole event. Scores are unaffected (they live in the results).
        """
        newest: Dict[tuple, int] = {}
        removed = 0
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT j.id, j.a_hash, j.b_hash, "
                "IFNULL(j.freeze_id, 0) AS f, r.hands_path "
                "FROM jobs j JOIN results r ON r.job_id=j.id "
                "WHERE j.status='done' AND j.kind=? ORDER BY j.id",
                (kind,),
            ).fetchall()
            for row in rows:
                newest[(row["f"], row["a_hash"], row["b_hash"])] = row["id"]
            for row in rows:
                key = (row["f"], row["a_hash"], row["b_hash"])
                if row["id"] == newest[key] or not row["hands_path"]:
                    continue
                try:
                    (self.root / row["hands_path"]).unlink(missing_ok=True)
                except OSError:
                    continue
                conn.execute(
                    "UPDATE results SET hands_path=NULL WHERE job_id=?",
                    (row["id"],),
                )
                removed += 1
        return removed

    def results(
        self, kind: str, freeze_id: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """One pooled result per pairing of a kind.

        A pairing played in several rounds (timed cycles) is combined into
        one result over all its deals. The job id, hands and finish time are
        those of its newest round.
        """
        query = (
            "SELECT j.id, j.a_hash, j.b_hash, j.deals, j.finished_at, "
            "j.round, r.data, r.hands_path "
            "FROM jobs j JOIN results r ON r.job_id=j.id "
            "WHERE j.status='done' AND j.kind=?"
        )
        params: List[Any] = [kind]
        if freeze_id is not None:
            query += " AND j.freeze_id=?"
            params.append(freeze_id)
        done_round = self.cycle_done() if kind == "ladder" else None
        if done_round is not None:
            query += " AND j.round<=?"
            params.append(done_round)
        query += " ORDER BY j.id"
        with self._conn() as conn:
            rows = conn.execute(query, params).fetchall()
        runs: Dict[tuple, List[Dict[str, Any]]] = {}
        for row in rows:
            run = {
                "job_id": row["id"],
                "a_hash": row["a_hash"],
                "b_hash": row["b_hash"],
                "deals": row["deals"],
                "hands_path": row["hands_path"],
                "finished_at": row["finished_at"],
                "round": row["round"],
                **json.loads(row["data"]),
            }
            runs.setdefault((row["a_hash"], row["b_hash"]), []).append(run)
        return [_pool_runs(group) for group in runs.values()]


def _pool_runs(runs: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Combines the rounds of one pairing (oldest first) into one row."""
    newest = dict(runs[-1])
    newest["rounds"] = len(runs)
    if len(runs) == 1:
        return newest
    total, mean, se = pool(
        [
            (
                run.get("deals_completed", 0),
                run.get("mean_bb"),
                run.get("se_bb"),
            )
            for run in runs
        ]
    )
    finite = not math.isinf(se)
    newest["mean_bb"] = mean
    newest["se_bb"] = se if finite else None
    newest["deals_completed"] = total
    newest["ci95_bb"] = ci95(se, total) if finite and total > 1 else None
    for key in (
        "deals",
        "deals_requested",
        "hands_played",
        "faults_a",
        "faults_b",
        "think_a",
        "think_b",
        "elapsed",
    ):
        newest[key] = sum(run.get(key) or 0 for run in runs)
    for key in ("disabled_a", "disabled_b"):
        newest[key] = next(
            (run[key] for run in reversed(runs) if run.get(key)), None
        )
    newest["status"] = (
        "complete"
        if all(run.get("status") == "complete" for run in runs)
        else "incomplete"
    )
    return newest
