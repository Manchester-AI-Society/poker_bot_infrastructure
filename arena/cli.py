"""Command line: ``python -m arena <command>``.

Commands for participants:
    match A B     play a duplicate match locally (the same code path and
                  scoring the competition uses)
    validate BOT  check that a bot loads and plays legally on time

Commands for the organiser (state lives under --root, default arena_data):
    submit TEAM SRC   add a bot version from a folder, file or git URL
    ladder            run the live ladder (pick up submissions, play
                      pairings, keep results/leaderboard.json current)
    freeze            snapshot the current versions for the final
    final             play the frozen round robin, write results/final.json
    leaderboard       print (and write) the current ranking
    status            show versions and the job queue
    retry-failed      re-queue pairings whose job crashed
    export            write the static results site (optionally serve it
                      or push it to a git host)
"""

from __future__ import annotations

import argparse
import sys
import threading
import time
from pathlib import Path
from typing import List, Optional

from . import leaderboard as board_module
from .duel import PairingConfig, PairingResult, play_pairing
from .export import (
    REPLAY_POLICIES,
    REVEAL_MODES,
    ExportError,
    ExportOptions,
    export_site,
    git_publish,
)
from .history import HandWriter
from .intake import SubmissionError, scan_directory, submit
from .scheduler import (
    Settings,
    enqueue_final,
    enqueue_ladder,
    freeze_submissions,
    run_pending,
)
from .specs import contestant_from_spec
from .store import Store
from .validate import smoke_test


def _fmt_bb(value: Optional[float]) -> str:
    return "n/a" if value is None else f"{value:+.3f}"


def describe_result(result: PairingResult) -> str:
    """Human-readable summary of a pairing."""
    lines = [
        f"{result.a}  vs  {result.b}   "
        f"({result.deals_completed} deals = {result.hands_played} hands, "
        f"{result.elapsed:.1f}s, status: {result.status})"
    ]
    if result.mean_bb is None:
        lines.append("  no completed deals")
        return "\n".join(lines)

    half = result.ci95_bb
    lines.append(
        f"  {result.a}: {_fmt_bb(result.mean_bb)} bb/hand "
        f"(95% CI {_fmt_bb(result.mean_bb - half)} .. "
        f"{_fmt_bb(result.mean_bb + half)})"
    )
    if result.mean_bb - half > 0:
        verdict = f"{result.a} is ahead (CI excludes 0)"
    elif result.mean_bb + half < 0:
        verdict = f"{result.b} is ahead (CI excludes 0)"
    else:
        verdict = "no significant difference yet (try more --deals)"
    lines.append(f"  -> {verdict}")
    lines.append(
        f"  faults: {result.a}={result.faults_a}, {result.b}="
        f"{result.faults_b}    think time: {result.a}={result.think_a:.1f}s, "
        f"{result.b}={result.think_b:.1f}s"
    )
    for label, reason, log in (
        (result.a, result.disabled_a, result.fault_log_a),
        (result.b, result.disabled_b, result.fault_log_b),
    ):
        if reason:
            lines.append(f"  !! {label} was replaced by always-fold: {reason}")
        if log:
            lines.append(f"  first fault of {label}: {log[0][:300]}")
    return "\n".join(lines)


def cmd_match(args: argparse.Namespace) -> int:
    log_dir = Path(args.log_dir)
    options = dict(
        log_dir=log_dir,
        move_timeout=args.move_timeout,
        max_faults=args.max_faults,
    )
    first = contestant_from_spec(args.bot_a, **options)
    second = contestant_from_spec(args.bot_b, **options)
    if first.name == second.name:
        first.name, second.name = first.name + "-1", second.name + "-2"

    config = PairingConfig(
        deals=args.deals,
        seed=args.seed,
        stack=args.stack,
        small_blind=args.small_blind,
        big_blind=args.big_blind,
        think_budget_per_deal=args.think_budget,
    )
    started = time.monotonic()
    if args.hands:
        with HandWriter(Path(args.hands)) as writer:
            result = play_pairing(first, second, config, writer.write)
        print(f"hand histories written to {args.hands}")
    else:
        result = play_pairing(first, second, config)
    print(describe_result(result))
    print(f"bot logs: {log_dir}/   ({time.monotonic() - started:.1f}s total)")
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    report = smoke_test(
        Path(args.bot),
        deals=args.deals,
        log_dir=Path(args.log_dir),
        move_timeout=args.move_timeout,
    )
    print(("OK: " if report.ok else "FAILED: ") + report.message)
    return 0 if report.ok else 1


def _settings(args: argparse.Namespace) -> Settings:
    kwargs = dict(
        deals=args.deals,
        move_timeout=args.move_timeout,
        max_faults=args.max_faults,
        think_budget_per_deal=args.think_budget,
        time_cap_seconds=args.time_cap,
    )
    if args.workers:
        kwargs["workers"] = args.workers
    return Settings(**kwargs)


def _publish(store: Store, kind: str) -> dict:
    board = board_module.compute(store, kind)
    name = "final.json" if kind == "final" else "leaderboard.json"
    board_module.write_json(board, store.root / "results" / name)
    return board


def cmd_submit(args: argparse.Namespace) -> int:
    store = Store(args.root)
    try:
        result = submit(
            store,
            args.team,
            args.source,
            validate=not args.no_validate,
            move_timeout=args.move_timeout,
        )
    except SubmissionError as exc:
        print(f"REJECTED: {exc}")
        return 1
    print(
        f"{result.status.upper()}: {result.team} @ {result.digest}: "
        f"{result.message}"
    )
    return 0 if result.accepted else 1


def cmd_ladder(args: argparse.Namespace) -> int:
    store = Store(args.root)
    settings = _settings(args)
    submissions = Path(args.submissions) if args.submissions else None

    last_scan = [float("-inf")]

    def tick() -> None:
        # Hashing every bot folder is not free: scan at most every
        # --interval seconds, not on every scheduler poll.
        due = time.monotonic() - last_scan[0] >= args.interval
        if submissions is not None and due:
            last_scan[0] = time.monotonic()
            for result in scan_directory(
                store, submissions, move_timeout=args.move_timeout
            ):
                print(
                    f"[submit] {result.team}: {result.status} "
                    f"{result.digest} - {result.message}"
                )
        enqueue_ladder(store, settings.deals)

    def progress() -> None:
        counts = store.job_counts("ladder")
        _publish(store, "ladder")
        print(
            f"[ladder] done={counts.get('done', 0)} "
            f"queued={counts.get('queued', 0)} "
            f"running={counts.get('running', 0)} "
            f"failed={counts.get('failed', 0)}"
        )

    while True:
        run_pending(
            store,
            settings,
            kinds=("ladder",),
            tick=tick,
            on_progress=progress,
        )
        board = _publish(store, "ladder")
        print(board_module.format_table(board))
        if args.once:
            return 0
        time.sleep(args.interval)


def cmd_freeze(args: argparse.Namespace) -> int:
    store = Store(args.root)
    freeze_id, excluded = freeze_submissions(
        store, move_timeout=args.move_timeout
    )
    members = store.freeze_members(freeze_id)
    print(f"freeze {freeze_id}: {len(members)} bots")
    for version in members:
        print(f"  {version.team:<20} {version.hash}")
    for team, reason in excluded:
        print(f"  EXCLUDED {team}: {reason}")
    return 0


def cmd_final(args: argparse.Namespace) -> int:
    store = Store(args.root)
    freeze_id = args.freeze_id or store.latest_freeze()
    if freeze_id is None:
        print("no freeze yet; run 'freeze' first")
        return 1
    settings = _settings(args)
    created = enqueue_final(store, freeze_id, settings.deals)
    print(f"final (freeze {freeze_id}): {created} pairings queued")

    def progress() -> None:
        counts = store.job_counts("final")
        print(
            f"[final] done={counts.get('done', 0)} "
            f"queued={counts.get('queued', 0)} "
            f"running={counts.get('running', 0)} "
            f"failed={counts.get('failed', 0)}"
        )

    run_pending(store, settings, kinds=("final",), on_progress=progress)
    board = board_module.compute(store, "final", freeze_id)
    board_module.write_json(board, store.root / "results" / "final.json")
    print(board_module.format_table(board))
    failed = store.job_counts("final").get("failed", 0)
    if failed:
        print(
            f"WARNING: {failed} pairings failed; see 'status', then "
            "'retry-failed' and run 'final' again"
        )
        return 1
    return 0


def cmd_leaderboard(args: argparse.Namespace) -> int:
    store = Store(args.root)
    board = _publish(store, args.kind)
    print(board_module.format_table(board))
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    store = Store(args.root)
    print("current versions:")
    for version in store.current_versions():
        print(f"  {version.team:<20} {version.hash}")
    for kind in ("ladder", "final"):
        print(f"{kind} jobs: {store.job_counts(kind) or 'none'}")
    freeze_id = store.latest_freeze()
    print(f"latest freeze: {freeze_id if freeze_id else 'none'}")
    return 0


def cmd_retry_failed(args: argparse.Namespace) -> int:
    count = Store(args.root).requeue_failed()
    print(f"{count} failed jobs cleared; the next run will queue them again")
    return 0


def _export_once(args: argparse.Namespace, options: ExportOptions) -> None:
    """One export pass, plus an optional git push; prints one line."""
    summary = export_site(args.root, args.out, options)
    stamp = time.strftime("%H:%M:%S")
    note = "updated" if summary.changed else "no change"
    print(
        f"[export {stamp}] {note}: {summary.teams} teams, "
        f"{summary.ladder_pairings} ladder / {summary.final_pairings} final "
        f"pairings, {summary.replay_files} replays "
        f"({summary.replay_bytes / 1e6:.1f} MB)"
    )
    if args.git_push:
        pushed = git_publish(args.out, f"Update results ({stamp})")
        if pushed:
            print(f"[export {stamp}] pushed to git")


def cmd_export(args: argparse.Namespace) -> int:
    from .serve import lan_address, make_server

    submit_text = args.submit_text
    if args.submit_text_file:
        submit_text = Path(args.submit_text_file).read_text(encoding="utf-8")
    options = ExportOptions(
        title=args.title,
        replays=args.replays,
        reveal=args.reveal,
        max_replay_hands=args.max_replay_hands,
        submit_text=submit_text,
    )
    try:
        options.validate()
        _export_once(args, options)
    except ExportError as exc:
        print(f"export failed: {exc}")
        return 1

    server = None
    if args.serve:
        server = make_server(args.out, args.host, args.serve)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        print(f"serving {args.out} at http://localhost:{args.serve}/")
        if args.host in ("0.0.0.0", "::"):
            address = lan_address()
            if address:
                print(
                    f"others on this network: http://{address}:{args.serve}/"
                )
        print("press Ctrl+C to stop")

    if not args.loop and server is None:
        return 0
    try:
        while True:
            time.sleep(args.loop or 3600)
            if args.loop:
                try:
                    _export_once(args, options)
                except ExportError as exc:
                    # A dropped network or a busy database must not end an
                    # event: report it and try again next time round.
                    print(f"[export] problem, will retry: {exc}")
    except KeyboardInterrupt:
        print("stopped")
    finally:
        if server is not None:
            server.shutdown()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m arena",
        description="Poker bot competition harness (heads-up, duplicate).",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    match = commands.add_parser(
        "match", help="play a duplicate match between two bots locally"
    )
    match.add_argument("bot_a", help="bot.py, bot directory, or @baseline")
    match.add_argument("bot_b", help="bot.py, bot directory, or @baseline")
    match.add_argument("--deals", type=int, default=100)
    match.add_argument("--seed", type=int, default=1)
    match.add_argument("--stack", type=int, default=2000)
    match.add_argument("--small-blind", type=int, default=10)
    match.add_argument("--big-blind", type=int, default=20)
    match.add_argument("--move-timeout", type=float, default=1.0)
    match.add_argument("--max-faults", type=int, default=20)
    match.add_argument(
        "--think-budget",
        type=float,
        default=0.2,
        help="seconds of thinking per deal, per bot per half",
    )
    match.add_argument("--hands", help="write hand histories (.jsonl.gz)")
    match.add_argument("--log-dir", default="arena_logs")
    match.set_defaults(handler=cmd_match)

    validate = commands.add_parser(
        "validate", help="check that a bot loads and plays legally"
    )
    validate.add_argument("bot")
    validate.add_argument("--deals", type=int, default=20)
    validate.add_argument("--move-timeout", type=float, default=1.0)
    validate.add_argument("--log-dir", default="arena_logs")
    validate.set_defaults(handler=cmd_validate)

    # -- organiser commands -------------------------------------------
    def organiser(name, help_text, handler, *, play=False):
        sub = commands.add_parser(name, help=help_text)
        sub.add_argument(
            "--root", default="arena_data", help="competition state folder"
        )
        sub.set_defaults(handler=handler)
        if play:
            sub.add_argument("--workers", type=int, default=0)
            sub.add_argument("--move-timeout", type=float, default=1.0)
            sub.add_argument("--max-faults", type=int, default=20)
            sub.add_argument("--think-budget", type=float, default=0.2)
            sub.add_argument(
                "--time-cap",
                type=float,
                default=1800.0,
                help="wall-clock seconds allowed per pairing",
            )
        return sub

    sub = organiser("submit", "add a bot version", cmd_submit)
    sub.add_argument("team")
    sub.add_argument("source", help="folder, bot.py or git URL")
    sub.add_argument("--no-validate", action="store_true")
    sub.add_argument("--move-timeout", type=float, default=1.0)

    sub = organiser("ladder", "run the live ladder", cmd_ladder, play=True)
    sub.add_argument("--deals", type=int, default=200)
    sub.add_argument(
        "--submissions",
        help="folder of <team>/bot.py directories to watch for changes",
    )
    sub.add_argument("--once", action="store_true")
    sub.add_argument("--interval", type=float, default=10.0)

    sub = organiser("freeze", "snapshot versions for the final", cmd_freeze)
    sub.add_argument("--move-timeout", type=float, default=1.0)

    sub = organiser(
        "final", "play the frozen round robin", cmd_final, play=True
    )
    sub.add_argument("--deals", type=int, default=1000)
    sub.add_argument("--freeze-id", type=int, default=0)

    sub = organiser("leaderboard", "show the ranking", cmd_leaderboard)
    sub.add_argument("--kind", choices=["ladder", "final"], default="ladder")

    sub = organiser("export", "write the static results site", cmd_export)
    sub.add_argument(
        "--out", default="arena_site", help="folder to write the site into"
    )
    sub.add_argument("--title", default="Poker Bot Competition")
    sub.add_argument(
        "--replays",
        choices=REPLAY_POLICIES,
        default="final",
        help="whose hand replays to publish (default: the final only)",
    )
    sub.add_argument(
        "--reveal",
        choices=REVEAL_MODES,
        default="showdown",
        help="show hole cards only at showdown (default) or always",
    )
    sub.add_argument(
        "--max-replay-hands",
        type=int,
        default=60,
        help="hands per pairing, biggest swings first; 0 = every hand",
    )
    sub.add_argument(
        "--submit-text", default="", help="how to submit, shown on the site"
    )
    sub.add_argument(
        "--submit-text-file", help="read the how-to-submit text from a file"
    )
    sub.add_argument(
        "--loop",
        type=float,
        default=0,
        metavar="SECONDS",
        help="keep exporting every SECONDS until Ctrl+C",
    )
    sub.add_argument(
        "--serve",
        type=int,
        default=0,
        metavar="PORT",
        help="also serve the site on this port",
    )
    sub.add_argument(
        "--host",
        default="127.0.0.1",
        help="address to serve on (0.0.0.0 lets others on the network in)",
    )
    sub.add_argument(
        "--git-push",
        action="store_true",
        help="commit and push --out (a git clone) after each export",
    )

    organiser("status", "show versions and the queue", cmd_status)
    organiser("retry-failed", "re-queue crashed jobs", cmd_retry_failed)
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    sys.exit(main())
