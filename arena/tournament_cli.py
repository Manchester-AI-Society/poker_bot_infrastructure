"""``python -m arena tournament ...``: the organiser's commands for the
two-round tournament.

    import FOLDER              (a top-level command) read the submission zips
    tournament status          who is in, and how far each round is
    tournament remove TEAM     take a team out before the draw
    tournament draw            draw round 1's groups
    tournament start-groups    begin round 1
    tournament run             play whatever is due (leave it running)
    tournament start-finals    begin round 2 (after round 1 is complete)
"""

from __future__ import annotations

import argparse
import time

from .store import Store
from .tournament import (
    Runner,
    TournamentError,
    TournamentSettings,
    cut_ties,
    draw,
    remove_team,
    start_finals,
    start_groups,
    state_of,
    status,
)


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


def _summary(store: Store) -> str:
    """One status line (no clock, so it changes only on progress)."""
    report = status(store)
    parts = [report["phase"], f"{len(report['teams'])} teams"]
    for kind, counts in (report.get("matches") or {}).items():
        total = sum(counts.values())
        parts.append(f"{kind}: {counts.get('done', 0)}/{total} played")
    return " | ".join(parts)


def cmd_run(args: argparse.Namespace) -> int:
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
        concurrency=args.concurrency or TournamentSettings().concurrency,
    )
    print(
        "playing whatever is due; start-groups / start-finals in another "
        "window.\nPress Ctrl+C to stop (matches in progress are replayed "
        "next time)."
    )
    runner = Runner(store, settings)
    last = ""
    try:
        while True:
            runner.step()
            line = _summary(store)
            if line != last:
                print(f"[{time.strftime('%H:%M:%S')}] {line}", flush=True)
                last = line
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("stopping")
        return 0
    finally:
        runner.close()


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
        if state["phase"] == "between":
            for note in cut_ties(store, state):
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
    print(f"phase: {report['phase']}")
    print(f"teams with a working bot: {len(report['teams'])}")
    for name in report["teams"]:
        print(f"  {name}")
    for group in report.get("groups", []):
        print(f"group {group['name']}: {', '.join(group['teams'])}")
    for kind, counts in report["matches"].items():
        print(f"{kind} matches: {counts}")
    if report.get("finalists"):
        print(f"finalists: {', '.join(report['finalists'])}")
    if report.get("champion"):
        print(f"champion: {report['champion']}")
    return 0


def add_tournament_parser(commands) -> None:
    top = commands.add_parser("tournament", help="the two-round tournament")
    sub = top.add_subparsers(dest="action", required=True)

    def command(name, help_text, handler):
        p = sub.add_parser(name, help=help_text)
        p.add_argument("--root", default="arena_data")
        p.set_defaults(handler=handler)
        return p

    command("status", "who is in and how far along", cmd_status)

    p = command("remove", "take a team out before the draw", cmd_remove)
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

    p = command("start-groups", "begin round 1", cmd_start_groups)
    p.add_argument(
        "--deals",
        type=int,
        default=100,
        help="deals per pairing (each is played twice)",
    )

    p = command("run", "play the matches that are due", cmd_run)
    p.add_argument("--move-timeout", type=float, default=1.0)
    p.add_argument("--max-faults", type=int, default=20)
    p.add_argument(
        "--think-budget",
        type=float,
        default=0.2,
        help="seconds per deal a bot may think in total",
    )
    p.add_argument("--time-cap", type=float, default=1800.0)
    p.add_argument(
        "--concurrency",
        type=int,
        default=0,
        help="matches at the same time (default: half the CPUs)",
    )

    p = command("start-finals", "begin round 2", cmd_start_finals)
    p.add_argument("--deals", type=int, default=200)
