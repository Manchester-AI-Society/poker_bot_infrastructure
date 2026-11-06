"""``python -m arena tournament ...``: the organiser's commands for the
two-round, websocket tournament.

    tournament open-registration   teams register themselves (join code)
    tournament close-registration  stop registrations (draw does too)
    tournament remove TEAM     remove a team before the draw
    tournament keys TEAMS      create teams and keys yourself instead
    tournament draw            draw round 1's groups
    tournament serve           listen for bots and play whatever is due
    tournament start-groups    begin round 1
    tournament start-finals    begin round 2 (after round 1 is complete)
    tournament status          who is connected and how far each round is
"""

from __future__ import annotations

import argparse
import socket
import time
from pathlib import Path
from typing import List

from .gateway import Gateway
from .store import Store
from .tournament import (
    Runner,
    TournamentError,
    TournamentSettings,
    close_registration,
    cut_ties,
    draw,
    generate_keys,
    open_registration,
    remove_team,
    start_finals,
    start_groups,
    state_of,
    status,
)


def read_team_names(path: Path) -> List[str]:
    """One team per line; blank lines and ``#`` comments are ignored."""
    names = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            names.append(line.split()[0])
    return names


def cmd_keys(args: argparse.Namespace) -> int:
    store = Store(args.root)
    names: List[str] = list(args.team or [])
    if args.teams_file:
        names += read_team_names(Path(args.teams_file))
    if not names and not args.rotate:
        print("give a teams file, --team NAME, or --rotate NAME")
        return 2
    out = Path(args.out)
    if out.exists() and out.stat().st_size and not args.force:
        print(f"{out} already exists; use --force to overwrite it")
        return 2
    try:
        keys = generate_keys(store, names, rotate=args.rotate or ())
    except TournamentError as exc:
        print(f"cannot do that: {exc}")
        return 2
    if not keys:
        print("no new teams or keys")
        return 0
    out.write_text(
        "".join(f"{team}  {key}\n" for team, key in sorted(keys.items())),
        encoding="utf-8",
    )
    print(
        f"{len(keys)} key(s) written to {out}. Each key is shown only there:\n"
        "give every team its own line privately, and do not commit the file."
    )
    return 0


def cmd_open_registration(args: argparse.Namespace) -> int:
    store = Store(args.root)
    try:
        code = open_registration(store, args.code, args.max_teams)
    except TournamentError as exc:
        print(f"cannot do that: {exc}")
        return 2
    print(f"registration is open (up to {args.max_teams} teams).")
    print(f"join code: {code}")
    print(
        "Announce the code and the address from 'tournament serve'. Each "
        "team runs:\n"
        "  python -m arena.connect --url ws://ADDRESS:PORT --team NAME "
        f"--code {code} bots/theirbot\n"
        "and is registered, and given its key, automatically. Registration "
        "ends when you draw the groups (or with 'close-registration')."
    )
    return 0


def cmd_close_registration(args: argparse.Namespace) -> int:
    store = Store(args.root)
    try:
        close_registration(store)
    except TournamentError as exc:
        print(f"cannot do that: {exc}")
        return 2
    print("registration is closed")
    return 0


def cmd_remove(args: argparse.Namespace) -> int:
    store = Store(args.root)
    try:
        remove_team(store, args.team)
    except TournamentError as exc:
        print(f"cannot do that: {exc}")
        return 2
    print(f"removed {args.team}")
    return 0


def cmd_draw(args: argparse.Namespace) -> int:
    store = Store(args.root)
    try:
        state = draw(
            store,
            group_size=args.group_size,
            advance=args.advance,
            seed=args.seed,
            redo=args.redo,
        )
    except TournamentError as exc:
        print(f"cannot do that: {exc}")
        return 2
    print(
        f"drawn with seed {state['seed']} (the same seed gives the same "
        f"draw); the best {state['advance']} of each group reach the finals"
    )
    for group in state["groups"]:
        print(f"  group {group['name']}: {', '.join(group['teams'])}")
    return 0


def _addresses(port: int) -> List[str]:
    found = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None):
            address = info[4][0]
            if info[0] == socket.AF_INET and not address.startswith("127."):
                found.add(address)
    except OSError:
        pass
    return [f"ws://{a}:{port}" for a in sorted(found)]


def cmd_serve(args: argparse.Namespace) -> int:
    store = Store(args.root)
    try:
        state_of(store)
    except TournamentError as exc:
        print(str(exc))
        return 2
    settings = TournamentSettings(
        move_timeout=args.move_timeout,
        max_faults=args.max_faults,
        think_budget_per_deal=args.think_budget,
        time_cap_seconds=args.time_cap,
        grace_seconds=args.grace,
        concurrency=args.concurrency,
    )
    store.clear_presence()
    try:
        gateway = Gateway(store, args.host, args.port).start()
    except RuntimeError as exc:
        print(str(exc))
        return 2
    print(f"listening on port {gateway.port}; teams connect to one of:")
    for address in _addresses(gateway.port) or [f"ws://HOST:{gateway.port}"]:
        print(f"  {address}")
    print("press Ctrl+C to stop (matches in progress are abandoned)")
    runner = Runner(store, gateway, settings)
    last = ""
    try:
        while True:
            runner.step()
            line = _summary(store, gateway)
            if line != last:
                print(line, flush=True)
                last = line
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("stopping")
        return 0
    finally:
        runner.close()
        gateway.stop()
        store.clear_presence()


def _summary(store: Store, gateway: Gateway) -> str:
    report = status(store)
    teams = report.get("teams", {})
    online = sum(1 for v in teams.values() if v)
    parts = [
        f"[{time.strftime('%H:%M:%S')}] {report['phase']}",
        f"{online}/{len(teams)} teams connected",
    ]
    for kind, counts in (report.get("matches") or {}).items():
        total = sum(counts.values())
        parts.append(f"{kind}: {counts.get('done', 0)}/{total} played")
    return " | ".join(parts)


def cmd_start_groups(args: argparse.Namespace) -> int:
    store = Store(args.root)
    try:
        made = start_groups(store, args.deals)
    except TournamentError as exc:
        print(f"cannot do that: {exc}")
        return 2
    print(f"round 1 started: {made} matches of {args.deals} deals queued")
    return 0


def cmd_start_finals(args: argparse.Namespace) -> int:
    store = Store(args.root)
    try:
        state = state_of(store)
        for note in (
            cut_ties(store, state) if state["phase"] == "between" else []
        ):
            print(f"note: {note}")
        made = start_finals(store, args.deals)
    except TournamentError as exc:
        print(f"cannot do that: {exc}")
        return 2
    print(f"finals started: {made} matches of {args.deals} deals queued")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    store = Store(args.root)
    report = status(store)
    if report["phase"] is None:
        print("no tournament yet; run 'tournament keys' first")
        return 0
    print(f"phase: {report['phase']}")
    if report["phase"] == "registration":
        print(
            "registration: "
            + ("open" if report["registration_open"] else "closed")
            + f", {len(report['teams'])} teams so far"
        )
    for name, online in report["teams"].items():
        print(f"  {'connected  ' if online else 'not online'} {name}")
    for group in report["groups"]:
        print(f"group {group['name']}: {', '.join(group['teams'])}")
    for kind, counts in report["matches"].items():
        print(f"{kind} matches: {counts}")
    if report["finalists"]:
        print(f"finalists: {', '.join(report['finalists'])}")
    if report["champion"]:
        print(f"champion: {report['champion']}")
    return 0


def add_tournament_parser(commands) -> None:
    top = commands.add_parser(
        "tournament", help="the two-round websocket tournament"
    )
    sub = top.add_subparsers(dest="action", required=True)

    def command(name, help_text, handler):
        p = sub.add_parser(name, help=help_text)
        p.add_argument("--root", default="arena_data")
        p.set_defaults(handler=handler)
        return p

    p = command("keys", "create teams and their secret keys", cmd_keys)
    p.add_argument("teams_file", nargs="?", help="one team name per line")
    p.add_argument("--team", action="append", help="a team name (repeatable)")
    p.add_argument(
        "--rotate",
        action="append",
        metavar="TEAM",
        help="give an existing team a new key",
    )
    p.add_argument(
        "--out",
        default="keys.txt",
        help="where the new keys are written (default keys.txt)",
    )
    p.add_argument("--force", action="store_true")

    p = command(
        "open-registration",
        "let teams register themselves with a join code",
        cmd_open_registration,
    )
    p.add_argument(
        "--code", help="a join code of your choice (default: random)"
    )
    p.add_argument("--max-teams", type=int, default=64)

    command(
        "close-registration", "stop teams registering", cmd_close_registration
    )

    p = command("remove", "remove a team before the draw", cmd_remove)
    p.add_argument("team")

    p = command("draw", "draw round 1's groups", cmd_draw)
    p.add_argument("--group-size", type=int, default=8)
    p.add_argument(
        "--advance",
        type=int,
        default=2,
        help="how many of each group reach the finals",
    )
    p.add_argument("--seed", type=int)
    p.add_argument("--redo", action="store_true")

    p = command("serve", "listen for bots and play the matches", cmd_serve)
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--move-timeout", type=float, default=1.0)
    p.add_argument("--max-faults", type=int, default=20)
    p.add_argument(
        "--think-budget",
        type=float,
        default=3.0,
        help="seconds per deal a bot may spend, network included",
    )
    p.add_argument("--time-cap", type=float, default=1800.0)
    p.add_argument(
        "--grace",
        type=float,
        default=300.0,
        help="seconds a round waits for a missing team before "
        "its matches are forfeited",
    )
    p.add_argument(
        "--concurrency",
        type=int,
        default=8,
        help="matches played at the same time",
    )

    p = command("start-groups", "begin round 1", cmd_start_groups)
    p.add_argument(
        "--deals",
        type=int,
        default=100,
        help="deals per pairing (each is played twice)",
    )

    p = command("start-finals", "begin round 2", cmd_start_finals)
    p.add_argument("--deals", type=int, default=200)

    command("status", "who is connected and how far along", cmd_status)
