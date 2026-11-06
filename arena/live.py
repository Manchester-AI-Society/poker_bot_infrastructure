"""The live feed: the match server's play, delayed, as static files.

The organiser's laptop runs the poker server (bots connect to it over
websockets). This module watches that server and writes what happened as plain
JSON for the website, **held back by a delay**: a hand is published only once
it finished ``delay`` seconds ago. The delay stops anyone using the site to see
what the other tables are doing while the tournament is on, and it matches how
rarely a static host can be redeployed.

Only public information is used: the tournament snapshot, the lobby and each
match's event log. Hole cards appear only for hands that went to a showdown
(the engine logs them nowhere else).

Pieces:

* :func:`parse_events` turns one match's event log into hands (pure).
* :class:`Feed` accumulates events from a running server.
* :func:`build_files` decides what is visible at a moment and renders files.
* :func:`export_live` writes them (and the site) into a folder.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .export import (
    SCHEMA_VERSION,
    ExportError,
    _sync_assets,
    _write_if_changed,
    git_publish,
)
from .jsonutil import dumps
from .roster import load_registered

DEFAULT_DELAY = 360.0  # seconds the public feed runs behind the real game
DEFAULT_INTERVAL = 300.0  # seconds between publications
MIN_INTERVAL = 60.0
MAX_HANDS_SHOWN = 80  # the latest hands kept in each table's file
PAGE = 1000

# Files of the other site modes that must not linger in a live site.
STALE_FILES = (
    "tournament.json",
    "leaderboard-ladder.json",
    "leaderboard-final.json",
    "pairings-ladder.json",
    "pairings-group.json",
    "pairings-final.json",
)


class ServerError(Exception):
    """The poker server could not be read."""


# -- reading the server -------------------------------------------------------


def fetch_json(base_url: str, path: str, timeout: float = 10.0) -> Any:
    request = urllib.request.Request(
        base_url.rstrip("/") + path,
        headers={"Accept": "application/json", "User-Agent": "poker-live"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        raise ServerError(f"{path}: HTTP {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        raise ServerError(f"{path}: {exc}") from exc


# -- turning an event log into hands (pure) ----------------------------------


def parse_events(events: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Hands, and how the match ended, from one match's event log.

    A hand is complete once its showdown event arrives; a hand still being
    played is left out. Times inside a hand are seconds from its start.
    """
    hands: List[Dict[str, Any]] = []
    current: Optional[Dict[str, Any]] = None
    level: Optional[Dict[str, int]] = None
    timed_out = set()
    created: Optional[float] = None
    players: List[str] = []
    ended: Optional[Dict[str, Any]] = None

    for event in events:
        kind = event.get("type")
        stamp = float(event.get("timestamp", 0))
        if kind == "match_created":
            created = stamp
            players = list(event.get("player_ids", []))
        elif kind == "blinds_increased":
            level = {
                "small": event["small_blind"],
                "big": event["big_blind"],
            }
        elif kind == "hand_started":
            blinds = event.get("blinds") or []
            amounts = sorted(b["amount"] for b in blinds)
            if level is None and amounts:
                level = {"small": amounts[0], "big": amounts[-1]}
            current = {
                "n": event["hand_number"],
                "t": stamp,
                "end": None,
                "players": event.get("players") or players,
                "dealer": event.get("dealer_index"),
                "stacks": event.get("stacks") or {},
                "blinds": blinds,
                "level": dict(level) if level else None,
                "eliminated": event.get("eliminated") or [],
                "steps": [],
                "showdown": None,
            }
            hands.append(current)
            timed_out.clear()
        elif current is None:
            continue
        elif kind == "timeout":
            timed_out.add(event.get("player_id"))
        elif kind == "action":
            player = event.get("player_id")
            current["steps"].append(
                {
                    "dt": round(stamp - current["t"], 2),
                    "type": "action",
                    "player": player,
                    "action": event.get("action"),
                    "amount": event.get("amount"),
                    "street": event.get("street"),
                    "pot": event.get("pot"),
                    "stack": event.get("stack"),
                    "bet": event.get("bet"),
                    "timeout": player in timed_out,
                }
            )
            timed_out.discard(player)
        elif kind == "street_advanced":
            current["steps"].append(
                {
                    "dt": round(stamp - current["t"], 2),
                    "type": "street",
                    "street": event.get("street"),
                    "board": event.get("board") or [],
                }
            )
        elif kind == "showdown":
            current["end"] = stamp
            current["showdown"] = {
                "dt": round(stamp - current["t"], 2),
                "results": event.get("results") or [],
                "stacks": event.get("stacks"),
                "hole_cards": event.get("hole_cards"),
                "board": event.get("board"),
            }
        elif kind == "match_ended":
            ended = {
                "t": stamp,
                "reason": event.get("reason"),
                "winners": list(event.get("winner_ids") or []),
            }
    return {
        "created": created,
        "players": players,
        "hands": [h for h in hands if h["end"] is not None],
        "ended": ended,
    }


# -- accumulating them from a server ------------------------------------------


@dataclass
class TableFeed:
    match_id: str
    round: int
    players: List[str]
    events: List[Dict[str, Any]] = field(default_factory=list)
    gone: bool = False  # the server no longer knows this match

    def refresh(self, base_url: str) -> None:
        """Fetches events not seen yet (the log is append-only)."""
        while not self.gone:
            try:
                page = fetch_json(
                    base_url,
                    f"/v1/matches/{self.match_id}/events"
                    f"?offset={len(self.events)}&limit={PAGE}",
                )
            except ServerError as exc:
                if "HTTP 404" in str(exc):
                    self.gone = True
                    return
                raise
            self.events.extend(page.get("events", []))
            if not page.get("has_more"):
                return


class Feed:
    """Everything seen so far from one server."""

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.snapshot: Dict[str, Any] = {}
        self.lobby: List[str] = []
        self.tables: Dict[str, TableFeed] = {}
        self.last_error: Optional[str] = None
        self.restarts = 0

    def poll(self) -> None:
        """Reads the tournament, the lobby and any new events."""
        try:
            snapshot = fetch_json(self.base_url, "/v1/tournament")
            lobby = fetch_json(self.base_url, "/v1/lobby").get("players", [])
        except ServerError as exc:
            self.last_error = str(exc)
            return
        self.last_error = None
        if snapshot.get("status") == "idle" and self.tables:
            # The server was reset: forget the old tournament.
            self.tables.clear()
            self.restarts += 1
        self.snapshot, self.lobby = snapshot, list(lobby)

        rounds = list(snapshot.get("completed_rounds") or [])
        rounds.append(snapshot.get("tables") or [])
        for number, tables in enumerate(rounds, start=1):
            for table in tables:
                match_id = table.get("match_id")
                if not match_id:
                    continue
                feed = self.tables.get(match_id)
                if feed is None:
                    feed = self.tables[match_id] = TableFeed(
                        match_id, number, list(table.get("player_ids", []))
                    )
                try:
                    feed.refresh(self.base_url)
                except ServerError as exc:
                    self.last_error = str(exc)


# -- what is visible at a moment -------------------------------------------


def table_view(
    feed: TableFeed, visible_until: float
) -> Optional[Dict[str, Any]]:
    """A table as the public feed shows it, or None if not visible yet."""
    parsed = parse_events(feed.events)
    created = parsed["created"]
    if created is None or created > visible_until:
        return None
    hands = [h for h in parsed["hands"] if h["end"] <= visible_until]
    ended = parsed["ended"]
    finished = bool(ended and ended["t"] <= visible_until)

    stacks: Dict[str, int] = {}
    if hands:
        last = hands[-1]
        stacks = dict(
            (last["showdown"] or {}).get("stacks") or last["stacks"] or {}
        )
    eliminated: List[str] = []
    for hand in hands:
        for player in hand["eliminated"]:
            if player not in eliminated:
                eliminated.append(player)
    for player, chips in stacks.items():
        if chips == 0 and player not in eliminated:
            eliminated.append(player)

    first = hands[0] if hands else None
    return {
        "match_id": feed.match_id,
        "round": feed.round,
        "players": feed.players,
        "status": "finished" if finished else "playing",
        "winners": list(ended["winners"]) if finished else [],
        "end_reason": ended["reason"] if finished else None,
        "hands_played": len(hands),
        "stacks": stacks,
        "eliminated": eliminated,
        "starting_stack": (
            max((first["stacks"] or {"": 0}).values()) if first else None
        ),
        "level": hands[-1]["level"] if hands else None,
        "hands": hands[-MAX_HANDS_SHOWN:],
    }


def build_files(
    feed: Feed,
    now: float,
    delay: float,
    info: Dict[str, Any],
    registered: Optional[List[str]] = None,
) -> Dict[str, str]:
    """The data files for the site, as of ``now``, ``delay`` seconds behind."""
    visible_until = now - delay
    snapshot = feed.snapshot or {}
    started = snapshot.get("status") in ("running", "finished")

    views: Dict[str, Dict[str, Any]] = {}
    for match_id, table in sorted(feed.tables.items()):
        view = table_view(table, visible_until)
        if view is not None:
            views[match_id] = view

    # A round is shown once any of its tables is; the champion once the final
    # table has finished in the delayed view.
    rounds: Dict[int, List[Dict[str, Any]]] = {}
    for view in views.values():
        rounds.setdefault(view["round"], []).append(
            {k: v for k, v in view.items() if k != "hands"}
        )
    last_round = max(rounds) if rounds else 0
    final_views = rounds.get(last_round, [])
    champion = None
    snapshot_champion = snapshot.get("champion")
    # The champion is shown only when the delayed view has reached the FINAL
    # round (the snapshot's last), and its single table has finished there. An
    # earlier round must never reveal who went on to win.
    final_round = len(snapshot.get("completed_rounds") or []) + 1
    if (
        snapshot_champion
        and last_round == final_round
        and len(snapshot.get("tables") or []) == 1
        and len(final_views) == 1
        and final_views[0]["status"] == "finished"
        and snapshot_champion in final_views[0]["winners"]
    ):
        champion = snapshot_champion
    if champion:
        status = "finished"
    elif views:
        status = "running"
    else:
        status = "starting" if started else "idle"

    entrants = list(snapshot.get("entrants") or []) if started else []
    out_names = {p for v in views.values() for p in v["eliminated"]}
    teams: Dict[str, str] = {}
    for name in registered or []:
        teams[name] = "registered"
    for name in feed.lobby:
        teams[name] = "in the lobby"
    for name in entrants:
        teams[name] = "playing"
    for name in out_names:
        if name in teams:
            teams[name] = "out"
    if champion:
        teams[champion] = "champion"

    live = {
        "schema": SCHEMA_VERSION,
        "status": status,
        "delay_seconds": delay,
        "visible_until": visible_until,
        "round": last_round,
        "rounds": [{"round": n, "tables": rounds[n]} for n in sorted(rounds)],
        "champion": champion,
        "entrants": entrants,
        "lobby": [] if started else list(feed.lobby),
    }
    files = {
        "live.json": dumps(live),
        "info.json": dumps(info),
        "teams.json": dumps(
            {
                "teams": [
                    {"team": name, "status": teams[name]}
                    for name in sorted(teams)
                ],
                "registrations": [],
            }
        ),
    }
    for match_id, view in views.items():
        files[f"tables/{match_id}.json"] = dumps(view)
    return files


# -- writing the site --------------------------------------------------------


@dataclass
class LiveOptions:
    server: str = "http://127.0.0.1:8000"
    delay: float = DEFAULT_DELAY
    interval: float = DEFAULT_INTERVAL
    title: str = "Poker Bot Competition"
    # What the Info page tells people (all optional).
    server_url: str = ""  # the public address bots connect to
    join_code: str = ""  # shown on the site only if the organiser passes it
    form_url: str = ""  # the backup submission form
    register_form: str = ""  # the team-name registration form (prefilled)
    registrations: str = ""  # that form's sheet, as CSV file or https address
    note: str = ""  # free text for the top of the Info page
    guide: str = ""  # markdown for the Info page
    event: Optional[Dict[str, Any]] = None  # the Home page (event.json)

    def validate(self) -> None:
        if self.delay < 0:
            raise ExportError("the delay cannot be negative")
        if self.interval < MIN_INTERVAL:
            raise ExportError(
                f"publishing more often than every {MIN_INTERVAL:.0f} seconds "
                "would use up a free host's deployments; pass a larger "
                "--interval"
            )
        for name in ("server", "server_url", "form_url"):
            value = getattr(self, name)
            if value and not value.startswith(("http://", "https://")):
                raise ExportError(f"{name} must start with http(s)://")


def load_event(path: str) -> Dict[str, Any]:
    """Reads and tidies the Home page text (event.json).

    Only the known fields survive, as short plain strings, so a typo in the
    file cannot break the page or smuggle anything into it.
    """
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        raise ExportError(f"cannot read the event file {path}: {exc}")
    if not isinstance(raw, dict):
        raise ExportError("the event file must hold one JSON object")

    def text(value: Any, limit: int = 600) -> str:
        return value.strip()[:limit] if isinstance(value, str) else ""

    def texts(value: Any, limit: int = 600) -> List[str]:
        items = value if isinstance(value, list) else []
        return [t for t in (text(v, limit) for v in items[:20]) if t]

    timeline = []
    for row in (raw.get("timeline") or [])[:30]:
        if isinstance(row, dict) and text(row.get("title")):
            timeline.append(
                {
                    "time": text(row.get("time"), 40),
                    "title": text(row.get("title"), 120),
                    "detail": text(row.get("detail")),
                }
            )
    return {
        "tagline": text(raw.get("tagline"), 200),
        "intro": texts(raw.get("intro"), 1200),
        "prize": text(raw.get("prize"), 200),
        "timeline": timeline,
        "rules": texts(raw.get("rules")),
        "contact": text(raw.get("contact")),
    }


def export_live(
    feed: Feed,
    out: Path,
    options: LiveOptions,
    *,
    now: Optional[float] = None,
    store=None,
) -> bool:
    """Writes the site and the delayed data into ``out``; True if changed."""
    options.validate()
    out = Path(out)
    now = time.time() if now is None else now
    out.mkdir(parents=True, exist_ok=True)
    changed = False
    _sync_assets(out)
    if not (out / ".nojekyll").exists():
        (out / ".nojekyll").write_text("", encoding="utf-8")

    registered: List[str] = []
    warning = None
    if options.registrations:
        registered, warning = load_registered(options.registrations, store)
    info = {
        "server_url": options.server_url or None,
        "join_code": options.join_code or None,
        "form_url": options.form_url or None,
        "delay_seconds": options.delay,
        "interval_seconds": options.interval,
        "note": options.note,
        "event": options.event,
    }
    files = build_files(feed, now, options.delay, info, registered)

    data = out / "data"
    for stale in STALE_FILES:
        path = data / stale
        if path.exists():
            path.unlink()
            changed = True
    tables_dir = data / "tables"
    wanted = {name for name in files if name.startswith("tables/")}
    if tables_dir.exists():
        for old in tables_dir.glob("*.json"):
            if f"tables/{old.name}" not in wanted:
                old.unlink()
                changed = True
    for name, text in files.items():
        changed = _write_if_changed(data / name, text) or changed

    guide_path = data / "submitting.md"
    if options.guide.strip():
        changed = _write_if_changed(guide_path, options.guide) or changed
    elif guide_path.exists():
        guide_path.unlink()
        changed = True

    import hashlib

    fingerprint = hashlib.sha256(
        "".join(files[name] for name in sorted(files)).encode()
        + options.guide.encode()
        + options.title.encode()
        + options.register_form.encode()
    ).hexdigest()[:16]
    manifest_path = data / "manifest.json"
    generated_at = now
    if manifest_path.exists():
        try:
            previous = json.loads(manifest_path.read_text(encoding="utf-8"))
        except ValueError:
            previous = {}
        if previous.get("fingerprint") == fingerprint:
            generated_at = previous.get("generated_at", now)
        else:
            changed = True
    else:
        changed = True
    manifest = {
        "schema": SCHEMA_VERSION,
        "mode": "live",
        "title": options.title,
        "submit_text": "",
        "has_guide": bool(options.guide.strip()),
        "registry_repo": None,
        "register_form": options.register_form or None,
        "fingerprint": fingerprint,
        "generated_at": generated_at,
        "kinds": [],
        "final_available": False,
        "teams": len(json.loads(files["teams.json"])["teams"]),
        "delay_seconds": options.delay,
    }
    _write_if_changed(manifest_path, dumps(manifest))
    if warning:
        print(f"warning: {warning}")
    return changed


def run_live(
    options: LiveOptions,
    out: Path,
    *,
    git_push: bool = False,
    once: bool = False,
    poll_seconds: float = 3.0,
    log=print,
    store=None,
) -> int:
    """Polls the server forever, publishing every ``interval`` seconds."""
    feed = Feed(options.server)
    last_publish = float("-inf")
    last_error = None
    try:
        while True:
            feed.poll()
            if feed.last_error != last_error:
                last_error = feed.last_error
                if last_error:
                    log(f"[live] cannot read the server: {last_error}")
                else:
                    log("[live] server reachable")
            due = time.monotonic() - last_publish >= options.interval
            if once or due:
                changed = export_live(feed, out, options, store=store)
                stamp = time.strftime("%H:%M:%S")
                log(
                    f"[live {stamp}] "
                    f"{'updated' if changed else 'no change'}: "
                    f"{len(feed.tables)} tables seen, "
                    f"{options.delay:.0f}s behind"
                )
                if git_push and changed:
                    try:
                        if git_publish(out, f"Live feed ({stamp})"):
                            log(f"[live {stamp}] pushed to git")
                    except ExportError as exc:
                        log(f"[live {stamp}] push failed: {exc}")
                last_publish = time.monotonic()
            if once:
                return 0
            time.sleep(poll_seconds)
    except KeyboardInterrupt:
        log("stopped")
        return 0


def describe(delay: float, interval: float) -> Tuple[str, str]:
    """Plain words for the organiser about what the settings mean."""
    per_day = 86400 / interval
    return (
        f"the site runs about {delay / 60:.1f} minutes behind the game",
        f"one publication every {interval:.0f}s is up to {per_day:.0f} a day "
        "(a free Vercel plan allows about 100 deployments a day)",
    )
