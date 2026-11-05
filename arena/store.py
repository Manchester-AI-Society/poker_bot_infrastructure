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
import secrets
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Sequence

from .procs import pid_alive, worker_pid

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
    created_at REAL NOT NULL, started_at REAL, finished_at REAL);
CREATE UNIQUE INDEX IF NOT EXISTS jobs_pair
    ON jobs(kind, IFNULL(freeze_id, 0), a_hash, b_hash)
    WHERE status != 'stale';
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
            conn.execute(
                "INSERT OR IGNORE INTO meta(key, value) VALUES (?, ?)",
                ("seed", str(secrets.randbits(48))),
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
    ) -> Optional[int]:
        """Queues a pairing; returns None if it already exists."""
        a_hash, b_hash = sorted((a_hash, b_hash))
        with self._conn() as conn:
            try:
                cursor = conn.execute(
                    "INSERT INTO jobs(kind, freeze_id, a_hash, b_hash, "
                    "deals, seed, status, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, 'queued', ?)",
                    (
                        kind,
                        freeze_id,
                        a_hash,
                        b_hash,
                        deals,
                        seed,
                        time.time(),
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

    def results(
        self, kind: str, freeze_id: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """Finished pairings of a kind, newest results only per pair."""
        query = (
            "SELECT j.id, j.a_hash, j.b_hash, j.deals, j.finished_at, "
            "r.data, r.hands_path "
            "FROM jobs j JOIN results r ON r.job_id=j.id "
            "WHERE j.status='done' AND j.kind=?"
        )
        params: List[Any] = [kind]
        if freeze_id is not None:
            query += " AND j.freeze_id=?"
            params.append(freeze_id)
        query += " ORDER BY j.id"
        with self._conn() as conn:
            rows = conn.execute(query, params).fetchall()
        return [
            {
                "job_id": row["id"],
                "a_hash": row["a_hash"],
                "b_hash": row["b_hash"],
                "deals": row["deals"],
                "hands_path": row["hands_path"],
                "finished_at": row["finished_at"],
                **json.loads(row["data"]),
            }
            for row in rows
        ]
