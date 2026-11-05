"""Static site export: turns the arena's files into a folder a browser reads.

``export_site`` reads the SQLite store and the hand histories and writes a
self-contained folder (the page assets from ``arena/site`` plus ``data/``
JSON). The folder can be served from the organiser's laptop or pushed to any
static host such as GitHub Pages; there is no server code.

What is published is decided here, in one place, because a public site must
not leak what a team's own logs contain:

* Bot tracebacks never leave the machine. Fault messages quote the bot's own
  exceptions (and so its source lines); the export keeps only a yes/no flag.
* Validation messages are cut to their last line (the exception itself).
* Replays follow a policy (``none``, ``final`` or ``all``), and hole cards are
  shown only when a hand reached showdown unless ``reveal="all"``.
* A deal's shuffle seed is published only with ``reveal="all"``: the seed
  reproduces every card of the deal, hidden ones included.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import time
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from .history import read_hands
from .jsonutil import dumps, write_atomic
from .leaderboard import compute
from .store import Store, Version

SCHEMA_VERSION = 1
SITE_DIR = Path(__file__).resolve().parent / "site"
# Files in the site source that are for development only.
_SOURCE_ONLY = ("package.json",)

REPLAY_POLICIES = ("none", "final", "all")
REVEAL_MODES = ("showdown", "all")
_STREET_CARDS = {"preflop": 0, "flop": 3, "turn": 4, "river": 5}
_MESSAGE_LIMIT = 140


class ExportError(Exception):
    """The export cannot run (bad option or no competition data)."""


@dataclass(frozen=True)
class ExportOptions:
    title: str = "Poker Bot Competition"
    replays: str = "final"
    reveal: str = "showdown"
    # Per pairing, the hands with the biggest swings; 0 publishes every hand.
    max_replay_hands: int = 60
    submit_text: str = ""
    # Markdown for the 'How to submit' page (normally SUBMITTING.md);
    # empty means the site has no such page.
    guide: str = ""

    def validate(self) -> None:
        if self.replays not in REPLAY_POLICIES:
            raise ExportError(f"replays must be one of {REPLAY_POLICIES}")
        if self.reveal not in REVEAL_MODES:
            raise ExportError(f"reveal must be one of {REVEAL_MODES}")
        if self.max_replay_hands < 0:
            raise ExportError("max_replay_hands cannot be negative")

    def fingerprint(self) -> str:
        return (
            f"{SCHEMA_VERSION}|{self.replays}|{self.reveal}"
            f"|{self.max_replay_hands}"
        )


@dataclass
class ExportSummary:
    changed: bool
    teams: int
    ladder_pairings: int
    final_pairings: int
    final_available: bool
    replay_files: int
    replay_bytes: int
    generated_at: float


# -- sanitising --------------------------------------------------------


# A Windows drive path (C:\x or C:/x) or a Unix path (/home/x/y). Web URLs
# must survive: "https://host/a/b" contains "s:/" and "/a/b", so a drive
# letter has to stand alone (not end a word) and not be followed by "//", and
# a Unix path cannot start right after ":" or "/" or a word character.
_PATH = re.compile(
    r"((?<!\w)[A-Za-z]:(?:\\|/(?!/))[^\s'\"]*"
    r"|(?<![\w.:/])/(?:[\w.-]+/)+[\w.-]*)"
)


def short_message(message: Optional[str]) -> str:
    """The exception line of a validation message, safe to publish.

    A stored message is a whole traceback. Its frames quote the submitting
    team's source lines and the organiser's file paths, so only the final
    exception line is kept (harness notes such as '; DISABLED: ...' are
    skipped) and anything that looks like a file path is blanked.
    """
    chosen = ""
    for line in reversed((message or "").splitlines()):
        text = line.strip()
        if not text or text.startswith(";") or line[:1].isspace():
            continue
        if text.startswith("Traceback"):
            continue
        chosen = text
        break
    chosen = _PATH.sub("<path>", chosen)
    if chosen.startswith("AgentFault: "):
        chosen = chosen[len("AgentFault: ") :]
    if len(chosen) > _MESSAGE_LIMIT:
        chosen = chosen[: _MESSAGE_LIMIT - 1] + "…"
    return chosen


def disabled_kind(reason: Optional[str]) -> Optional[str]:
    """Reduces a harness 'disabled' reason to a category, or None."""
    if not reason:
        return None
    lowered = reason.lower()
    if "time budget" in lowered:
        return "time"
    if "fault" in lowered:
        return "faults"
    if "start" in lowered or "load" in lowered:
        return "start"
    return "other"


def verdict(mean: Optional[float], half: Optional[float]) -> str:
    """'a', 'b' or 'tie' from A's mean and its 95% half-width."""
    if mean is None or half is None:
        return "tie"
    if mean - half > 0:
        return "a"
    if mean + half < 0:
        return "b"
    return "tie"


# -- replays -----------------------------------------------------------


def _board_reached(hand: Dict[str, Any]) -> List[str]:
    """The board cards that were actually dealt in this hand."""
    board = list(hand["board"])
    if hand["ended_by"] == "showdown":
        return board
    last = "preflop"
    for action in hand["actions"]:
        last = action["street"]
    return board[: _STREET_CARDS.get(last, 0)]


def public_hand(hand: Dict[str, Any], reveal: str) -> Dict[str, Any]:
    """The browser-safe, compact form of one hand record.

    Actions are ``[seat, action, amount, street, fault]`` where ``fault`` is
    1 when the bot misbehaved on that move (the reason stays private).
    """
    showdown = hand["ended_by"] == "showdown"
    results: List[List[Any]] = [[0, ""] for _ in hand["seats"]]
    for result in hand["results"]:
        seat = int(str(result["player_id"]).removeprefix("seat"))
        results[seat] = [result["winnings"], result["hand"]]
    out: Dict[str, Any] = {
        "n": hand["hand_index"],
        "deal": hand.get("deal"),
        "o": hand.get("orientation"),
        "seats": list(hand["seats"]),
        "stacks": list(hand["stacks"]),
        "sb": hand["small_blind"],
        "bb": hand["big_blind"],
        "dealer": hand["dealer_seat"],
        "hole": (
            hand["hole_cards"] if (showdown or reveal == "all") else None
        ),
        "board": _board_reached(hand),
        "actions": [
            [
                a["seat"],
                a["action"],
                a["amount"],
                a["street"],
                1 if a.get("fault") else 0,
            ]
            for a in hand["actions"]
        ],
        "end": hand["ended_by"],
        "res": results,
        "net": list(hand["net"]),
    }
    if reveal == "all":
        # A seed reproduces the whole shuffle, so it is only ever published
        # when every card is public anyway. Strings: JS loses 64-bit ints.
        out["seed"] = str(hand["deal_seed"])
    return out


def select_hands(
    hands: Sequence[Dict[str, Any]], limit: int
) -> List[Dict[str, Any]]:
    """The ``limit`` hands with the biggest chip swings, in play order."""
    if limit <= 0 or len(hands) <= limit:
        return list(hands)

    def swing(hand: Dict[str, Any]) -> int:
        return max(abs(value) for value in hand["net"])

    # Biggest swing first; among equals prefer hands that reached showdown
    # (more to watch than a fold), then play order for a stable choice.
    ranked = sorted(
        hands,
        key=lambda h: (
            -swing(h),
            h["ended_by"] != "showdown",
            h["hand_index"],
        ),
    )
    chosen = ranked[:limit]
    return sorted(chosen, key=lambda h: h["hand_index"])


def build_replay(
    store: Store,
    row: Dict[str, Any],
    a_team: str,
    b_team: str,
    kind: str,
    options: ExportOptions,
) -> Optional[Dict[str, Any]]:
    """The public replay file for one pairing, or None if unavailable."""
    if not row.get("hands_path"):
        return None
    path = store.root / row["hands_path"]
    if not path.exists():
        return None
    try:
        hands = list(read_hands(path))
    except (OSError, EOFError, ValueError, zlib.error):
        # A damaged hand file costs that match its replay, never the whole
        # publisher (a bad file here once killed the export loop).
        return None
    if not hands:
        return None
    chosen = select_hands(hands, options.max_replay_hands)
    return {
        "schema": SCHEMA_VERSION,
        "id": f"{kind}-{row['job_id']}",
        "kind": kind,
        "a": a_team,
        "b": b_team,
        "reveal": options.reveal,
        "total_hands": len(hands),
        "shown": len(chosen),
        "selection": "all" if len(chosen) == len(hands) else "swings",
        "bb": hands[0]["big_blind"],
        "hands": [public_hand(hand, options.reveal) for hand in chosen],
    }


# -- the export --------------------------------------------------------


def _pairing_entries(
    store: Store,
    kind: str,
    members: Sequence[Version],
    freeze_id: Optional[int],
) -> tuple[List[Dict[str, Any]], Dict[str, Dict[str, Any]]]:
    """Public pairing entries (newest first) and their raw rows by id."""
    by_hash = {version.hash: version for version in members}
    entries: List[Dict[str, Any]] = []
    rows: Dict[str, Dict[str, Any]] = {}
    for row in store.results(kind, freeze_id):
        first = by_hash.get(row["a_hash"])
        second = by_hash.get(row["b_hash"])
        if first is None or second is None:
            continue
        mean = row.get("mean_bb")
        half = row.get("ci95_bb")
        entries.append(
            {
                "id": f"{kind}-{row['job_id']}",
                "job_id": row["job_id"],
                "kind": kind,
                "a": first.team,
                "b": second.team,
                "deals": row["deals"],
                "deals_completed": row["deals_completed"],
                "hands": row["hands_played"],
                "mean_bb": mean,
                "ci95_bb": half,
                "verdict": verdict(mean, half),
                "faults_a": row["faults_a"],
                "faults_b": row["faults_b"],
                "disabled_a": disabled_kind(row.get("disabled_a")),
                "disabled_b": disabled_kind(row.get("disabled_b")),
                "status": row["status"],
                "finished_at": row.get("finished_at"),
                "replay": None,
            }
        )
        rows[f"{kind}-{row['job_id']}"] = row
    entries.sort(key=lambda e: (-(e["finished_at"] or 0), -e["job_id"]))
    return entries, rows


def _team_entries(
    store: Store, final_members: Sequence[Version]
) -> List[Dict[str, Any]]:
    frozen = {version.team: version.hash for version in final_members}
    current = {
        version.team: version.hash for version in store.current_versions()
    }
    grouped: Dict[str, List[Version]] = {}
    for version in store.all_versions():
        grouped.setdefault(version.team, []).append(version)
    # A team whose repository could never be fetched has no version yet, but
    # must still be listed, with the reason, so its members can see it.
    sync = store.sync_statuses()
    teams = []
    for team in sorted(set(grouped) | set(sync)):
        versions = grouped.get(team, [])
        status = sync.get(team)
        teams.append(
            {
                "team": team,
                "current": current.get(team),
                "frozen": frozen.get(team),
                "sync": (
                    {
                        "status": status["status"],
                        "message": short_message(status["message"]),
                        "at": status["at"],
                    }
                    if status
                    else None
                ),
                "versions": [
                    {
                        "hash": version.hash,
                        "status": version.status,
                        "message": short_message(version.message),
                        "created_at": version.created_at,
                    }
                    for version in versions
                ],
            }
        )
    return teams


def _sync_assets(out: Path) -> None:
    """Copies the page assets, touching only files whose bytes changed."""
    for source in SITE_DIR.rglob("*"):
        if source.is_dir() or source.name in _SOURCE_ONLY:
            continue
        target = out / source.relative_to(SITE_DIR)
        data = source.read_bytes()
        if target.exists() and target.read_bytes() == data:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)


def _write_if_changed(path: Path, text: str) -> bool:
    if path.exists() and path.read_text(encoding="utf-8") == text:
        return False
    write_atomic(path, text)
    return True


def _export_replays(
    store: Store,
    out: Path,
    options: ExportOptions,
    pairings: Dict[str, List[Dict[str, Any]]],
    rows: Dict[str, Dict[str, Any]],
) -> tuple[int, int, bool]:
    """Writes replay files; returns (count, total bytes, anything changed)."""
    folder = out / "data" / "replays"
    policy_file = folder / ".policy"
    changed = False
    if folder.exists() and (
        not policy_file.exists()
        or policy_file.read_text(encoding="utf-8") != options.fingerprint()
    ):
        shutil.rmtree(folder)
        changed = True

    wanted: set[Path] = set()
    for kind, entries in pairings.items():
        if options.replays == "none" or (
            options.replays == "final" and kind != "final"
        ):
            continue
        for entry in entries:
            target = folder / f"{entry['id']}.json"
            if not target.exists():
                replay = build_replay(
                    store,
                    rows[entry["id"]],
                    entry["a"],
                    entry["b"],
                    kind,
                    options,
                )
                if replay is None:
                    continue
                write_atomic(target, dumps(replay))
                changed = True
            wanted.add(target)
            entry["replay"] = f"data/replays/{entry['id']}.json"

    if folder.exists():
        for stale in folder.glob("*.json"):
            if stale not in wanted:
                stale.unlink()
                changed = True
        write_atomic(policy_file, options.fingerprint())
    total = sum(path.stat().st_size for path in wanted)
    return len(wanted), total, changed


def export_site(
    root: Path | str, out: Path | str, options: ExportOptions
) -> ExportSummary:
    """Writes the static site for the competition in ``root`` to ``out``."""
    options.validate()
    root, out = Path(root), Path(out)
    if not (root / "arena.sqlite").exists():
        raise ExportError(f"no competition data found in {root}")
    store = Store(root)
    changed = False

    # Page assets first, then data, then the manifest: a page that polls the
    # manifest only sees a new version once everything it points to exists.
    out.mkdir(parents=True, exist_ok=True)
    _sync_assets(out)
    if not (out / ".nojekyll").exists():
        (out / ".nojekyll").write_text("", encoding="utf-8")

    data = out / "data"
    freeze_id = store.latest_freeze()
    final_members = store.freeze_members(freeze_id) if freeze_id else []
    boards: Dict[str, Dict[str, Any]] = {"ladder": compute(store, "ladder")}
    if freeze_id is not None:
        boards["final"] = compute(store, "final", freeze_id)

    pairings: Dict[str, List[Dict[str, Any]]] = {}
    rows: Dict[str, Dict[str, Any]] = {}
    pairings["ladder"], found = _pairing_entries(
        store, "ladder", store.current_versions(), None
    )
    rows.update(found)
    if freeze_id is not None:
        pairings["final"], found = _pairing_entries(
            store, "final", final_members, freeze_id
        )
        rows.update(found)

    count, size, replays_changed = _export_replays(
        store, out, options, pairings, rows
    )
    changed = changed or replays_changed

    files: Dict[str, str] = {}
    for kind, board in boards.items():
        board = dict(board)
        board.pop("generated_at", None)  # the manifest carries the time
        files[f"leaderboard-{kind}.json"] = dumps(board)
        files[f"pairings-{kind}.json"] = dumps(pairings[kind])
    files["teams.json"] = dumps({"teams": _team_entries(store, final_members)})
    if "final" not in boards:
        for name in ("leaderboard-final.json", "pairings-final.json"):
            stale = data / name
            if stale.exists():
                stale.unlink()
                changed = True

    for name, text in files.items():
        changed = _write_if_changed(data / name, text) or changed

    # The how-to-submit guide travels with the site as plain markdown;
    # the page turns it into elements itself (never as raw markup).
    guide_path = data / "submitting.md"
    if options.guide.strip():
        changed = _write_if_changed(guide_path, options.guide) or changed
    elif guide_path.exists():
        guide_path.unlink()
        changed = True

    fingerprint = hashlib.sha256(
        "".join(files[name] for name in sorted(files)).encode()
        + options.fingerprint().encode()
        + options.title.encode()
        + options.submit_text.encode()
        + options.guide.encode()
    ).hexdigest()[:16]
    generated_at = time.time()
    manifest_path = data / "manifest.json"
    if manifest_path.exists():
        try:
            previous = json.loads(manifest_path.read_text(encoding="utf-8"))
        except ValueError:
            previous = {}
        if previous.get("fingerprint") == fingerprint:
            generated_at = previous.get("generated_at", generated_at)
        else:
            changed = True
    else:
        changed = True

    manifest = {
        "schema": SCHEMA_VERSION,
        "title": options.title,
        "submit_text": options.submit_text,
        "has_guide": bool(options.guide.strip()),
        "fingerprint": fingerprint,
        "generated_at": generated_at,
        "kinds": list(boards),
        "final_available": "final" in boards,
        "replays": {
            "policy": options.replays,
            "reveal": options.reveal,
            "max_per_pairing": options.max_replay_hands,
        },
        "teams": len(boards["ladder"]["teams"]),
    }
    _write_if_changed(manifest_path, dumps(manifest))
    return ExportSummary(
        changed=changed,
        teams=len(boards["ladder"]["teams"]),
        ladder_pairings=len(pairings["ladder"]),
        final_pairings=len(pairings.get("final", [])),
        final_available="final" in boards,
        replay_files=count,
        replay_bytes=size,
        generated_at=generated_at,
    )


# -- publishing --------------------------------------------------------


def git_publish(out: Path | str, message: str) -> bool:
    """Commits and pushes ``out`` (a git work tree). True if it pushed.

    A push that fails (say the network dropped) leaves its commit in place,
    and the next call pushes it, so a flaky connection during an event costs
    nothing but time. Raises ExportError with git's own message on failure.
    """
    out = str(out)

    def git(*args: str, check: bool = True) -> subprocess.CompletedProcess:
        done = subprocess.run(
            ["git", "-C", out, *args],
            capture_output=True,
            text=True,
            timeout=300,
        )
        if check and done.returncode != 0:
            raise ExportError(
                f"git {' '.join(args)} failed: "
                f"{(done.stderr or done.stdout).strip()}"
            )
        return done

    if git("rev-parse", "--is-inside-work-tree").stdout.strip() != "true":
        raise ExportError(f"{out} is not a git work tree")
    git("add", "-A")
    if git("status", "--porcelain").stdout.strip():
        git("commit", "-q", "-m", message)
    ahead = git("rev-list", "--count", "@{u}..HEAD", check=False)
    if ahead.returncode == 0 and ahead.stdout.strip() == "0":
        return False  # nothing committed that the remote lacks
    git("push", "-q")
    return True
