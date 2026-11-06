"""Command line: ``python -m arena <command>``.

Commands for participants:
    match A B     play a duplicate match locally (the same code path and
                  scoring the competition uses)
    validate BOT  check that a bot loads and plays legally on time
    pack BOT      check a bot and write the .pkl you upload in the form

Commands for the organiser (state lives under --root, default arena_data):
    import FOLDER     import the .pkl files the form collected
    submit TEAM SRC   add a bot version from a folder, file or git URL
    sync              pull every team's bot from its own git repository, as
                      listed in a teams file (and keep doing it)
    ladder            run the live ladder (pick up submissions, play
                      pairings, keep results/leaderboard.json current)
    freeze            snapshot the current versions for the final
    final             play the frozen round robin, write results/final.json
    leaderboard       print (and write) the current ranking
    status            show versions and the job queue
    retry-failed      re-queue pairings whose job crashed
    export            write the static results site (optionally serve it
                      or push it to a git host)
    tournament ...    the two-round tournament (draw, start-groups, run,
                      start-finals, status, remove)
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
    load_event,
)
from .history import HandWriter
from .intake import SubmissionError, scan_directory, submit
from .registry import GitHubError, GitHubIssues, Registry
from .scheduler import (
    Settings,
    enqueue_final,
    enqueue_ladder,
    freeze_submissions,
    run_pending,
    run_round,
)
from .specs import contestant_from_spec
from .store import Store
from .sync import (
    CombinedSources,
    Reporter,
    TeamsFile,
    TeamsFileError,
    start_background,
    sync_teams,
)
from .tournament_cli import add_tournament_parser
from .validate import smoke_test

_ROOT = Path(__file__).resolve().parents[1]
# The 'How to submit' page: SUBMITTING.md when there is one, else the README.
DEFAULT_GUIDE = next(
    (p for p in (_ROOT / "SUBMITTING.md", _ROOT / "README.md") if p.is_file()),
    _ROOT / "README.md",
)
ORGANISER_HEADING = "\n## For the organiser"
DEFAULT_EVENT = _ROOT / "event.json"


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


def cmd_pack(args: argparse.Namespace) -> int:
    from .package import PackError, pack

    try:
        result = pack(
            Path(args.bot),
            args.team,
            Path(args.out),
            validate=not args.no_validate,
            log=print,
        )
    except PackError as exc:
        print(f"cannot pack: {exc}")
        return 1
    print(
        f"OK: {result.path} ({result.bytes / 1024:.0f} KB, "
        f"checksum {result.digest}).\n"
        "Upload that file in the submission form. To change your bot, pack "
        "it again and upload the new file: the newest one is played."
    )
    return 0


def cmd_import(args: argparse.Namespace) -> int:
    from .package import find_submissions, import_submissions

    folder = Path(args.folder)
    if not folder.exists():
        print(f"not found: {folder}")
        return 2
    if not find_submissions(folder):
        print(f"no .pkl files under {folder}")
        return 2
    from .tournament import ensure_tournament

    store = Store(args.root)
    ensure_tournament(store)
    results = import_submissions(store, folder, validate=not args.no_validate)
    bad = 0
    for r in results:
        who = r.team or "(unknown team)"
        print(f"  {r.status.upper():<10} {who:<20} {r.file}: {r.message}")
        bad += r.status in ("invalid", "rejected")
    teams = {v.team for v in store.current_versions()}
    print(
        f"{len(results)} files read: {len(teams)} teams ready, "
        f"{bad} problem(s)."
    )
    return 1 if bad else 0


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
            branch=args.branch,
        )
    except SubmissionError as exc:
        print(f"REJECTED: {exc}")
        return 1
    print(
        f"{result.status.upper()}: {result.team} @ {result.digest}: "
        f"{result.message}"
    )
    return 0 if result.accepted else 1


def _team_sources(args: argparse.Namespace, store: Store):
    """The teams to pull: a teams file, the registry, or both (None: neither).

    Raises TeamsFileError for a bad teams file or registry name.
    """
    parts = []
    if args.teams:
        parts.append(TeamsFile(args.teams))
    if args.registry:
        try:
            client = GitHubIssues(args.registry)
        except GitHubError as exc:
            raise TeamsFileError(str(exc)) from exc
        parts.append(
            Registry(
                client,
                store,
                open_registration=args.open_registration,
                max_per_user=args.max_per_user,
                feedback=not args.no_feedback,
            )
        )
    if not parts:
        return None
    return parts[0] if len(parts) == 1 else CombinedSources(*parts)


def _wait(seconds: float) -> None:
    """Sleeps in short steps so Ctrl+C is answered promptly."""
    deadline = time.monotonic() + seconds
    while True:
        left = deadline - time.monotonic()
        if left <= 0:
            return
        time.sleep(min(1.0, left))


def cmd_ladder(args: argparse.Namespace) -> int:
    store = Store(args.root)
    settings = _settings(args)
    cycling = args.cycle is not None
    if cycling and args.cycle <= 0:
        print("--cycle must be a number of seconds above zero")
        return 2
    submissions = Path(args.submissions) if args.submissions else None
    sync_stop = None
    try:
        teams = _team_sources(args, store)
        sources = teams.current() if teams is not None else None
    except TeamsFileError as exc:
        print(f"cannot use the teams: {exc}")
        return 2
    if teams is not None:
        sync_args = dict(
            move_timeout=args.move_timeout, clone_timeout=args.clone_timeout
        )
        reporter = Reporter()
        # One pass now, so the first ladder already includes every team.
        for line in reporter.lines(sync_teams(store, sources, **sync_args)):
            print(line)
        if not args.once:
            sync_stop = start_background(
                store,
                teams,
                args.sync_interval,
                reporter=reporter,
                **sync_args,
            )

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
        if not cycling:
            # A cycle queues every pairing itself, once per round.
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

    try:
        while True:
            if cycling:
                started = time.monotonic()
                round_no, finished = run_round(store, settings, tick=tick)
                board = _publish(store, "ladder")
                print(board_module.format_table(board))
                took = time.monotonic() - started
                print(
                    f"[cycle {round_no}] {finished} pairings played in "
                    f"{took:.0f}s"
                )
                if args.once:
                    return 0
                spare = args.cycle - took
                if spare <= 0:
                    print(
                        f"[cycle {round_no}] took longer than --cycle "
                        f"({args.cycle:.0f}s): starting the next at once. "
                        "Lower --deals or raise --cycle."
                    )
                else:
                    print(f"[cycle {round_no}] next in {spare:.0f}s")
                    _wait(spare)
                continue
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
    finally:
        if sync_stop is not None:
            sync_stop.set()


def cmd_sync(args: argparse.Namespace) -> int:
    store = Store(args.root)
    try:
        teams = _team_sources(args, store)
        if teams is None:
            print("give --teams FILE, --registry OWNER/REPO, or both")
            return 2
        teams.current()
    except TeamsFileError as exc:
        print(f"cannot use the teams: {exc}")
        return 2
    reporter = Reporter()
    options = dict(
        move_timeout=args.move_timeout, clone_timeout=args.clone_timeout
    )
    try:
        while True:
            results = sync_teams(store, teams.current(), **options)
            for line in reporter.lines(results):
                print(line)
            if args.once:
                problems = [r for r in results if not r.ok]
                if problems:
                    print(
                        f"{len(problems)} of {len(results)} teams have "
                        "a problem (listed above)"
                    )
                return 1 if problems else 0
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("stopped")
        return 0


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
    if summary.warning:
        print(f"[export {stamp}] warning: {summary.warning}")
    note = "updated" if summary.changed else "no change"
    if summary.phase is not None:
        shown = []
        if summary.ladder_pairings:
            shown.append(f"{summary.ladder_pairings} group matches")
        if summary.final_pairings:
            shown.append(f"{summary.final_pairings} final matches")
        print(
            f"[export {stamp}] {note}: tournament {summary.phase}, "
            f"{summary.teams} teams; published: "
            f"{', '.join(shown) or 'no results yet'}, "
            f"{summary.replay_files} replays"
        )
    else:
        print(
            f"[export {stamp}] {note}: {summary.teams} teams, "
            f"{summary.ladder_pairings} ladder / "
            f"{summary.final_pairings} final pairings, "
            f"{summary.replay_files} replays "
            f"({summary.replay_bytes / 1e6:.1f} MB)"
        )
    if args.git_push:
        pushed = git_publish(args.out, f"Update results ({stamp})")
        if pushed:
            print(f"[export {stamp}] pushed to git")


def _export_pass(
    args: argparse.Namespace, options: ExportOptions, *, keep_going: bool
) -> bool:
    """One export pass; True if it worked.

    With ``keep_going`` (running in a loop) no error may escape: a dropped
    network, a busy database or one unreadable file must not end an event.
    The problem is printed and the next pass tries again. Without it, an
    unexpected error is raised so a one-off run fails loudly.
    """
    try:
        _export_once(args, options)
        return True
    except ExportError as exc:
        label = (
            "[export] problem, will retry" if keep_going else "export failed"
        )
        print(f"{label}: {exc}", flush=True)
    except Exception as exc:
        if not keep_going:
            raise
        print(
            f"[export] unexpected problem, will retry: "
            f"{type(exc).__name__}: {exc}",
            flush=True,
        )
    return False


def cmd_export(args: argparse.Namespace) -> int:
    from .serve import lan_address, make_server

    submit_text = args.submit_text
    if args.submit_text_file:
        submit_text = Path(args.submit_text_file).read_text(encoding="utf-8")
    guide = ""
    if not args.no_guide:
        guide_path = Path(args.guide) if args.guide else DEFAULT_GUIDE
        if guide_path.is_file():
            # The organiser's notes are not for the public page.
            guide = guide_path.read_text(encoding="utf-8-sig").split(
                ORGANISER_HEADING
            )[0]
        elif args.guide:
            print(f"export failed: cannot read the guide {guide_path}")
            return 1
    event = None
    event_path = args.event_file or (
        str(DEFAULT_EVENT) if DEFAULT_EVENT.is_file() else ""
    )
    if event_path and not args.no_event:
        try:
            event = load_event(event_path)
        except ExportError as exc:
            print(f"export failed: {exc}")
            return 1
    options = ExportOptions(
        title=args.title,
        replays=args.replays,
        reveal=args.reveal,
        max_replay_hands=args.max_replay_hands,
        submit_text=submit_text,
        guide=guide,
        event=event,
        registry_repo=args.registry_repo or "",
        registrations=args.registrations or "",
        register_form=args.register_form or "",
    )
    try:
        options.validate()
    except ExportError as exc:
        print(f"export failed: {exc}")
        return 1
    # In a loop nothing a pass does may end it, including the first pass
    # (the network can be down at the start); a single run still fails.
    first_ok = _export_pass(args, options, keep_going=bool(args.loop))
    if not first_ok and not args.loop:
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
                _export_pass(args, options, keep_going=True)
    except KeyboardInterrupt:
        print("stopped")
    finally:
        if server is not None:
            server.shutdown()
    return 0


def _registry_options(sub: argparse.ArgumentParser) -> None:
    sub.add_argument(
        "--registry",
        metavar="OWNER/REPO",
        help="GitHub repository whose issues are team registrations",
    )
    sub.add_argument(
        "--open-registration",
        action="store_true",
        help="accept registrations without the organiser's 'approved' label "
        "(ownership of the repository is still checked)",
    )
    sub.add_argument(
        "--max-per-user",
        type=int,
        default=1,
        help="teams one GitHub account may register (default 1)",
    )
    sub.add_argument(
        "--no-feedback",
        action="store_true",
        help="do not comment on registration issues",
    )


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

    pack = commands.add_parser(
        "pack",
        help="check your bot and write the .pkl you upload in the form",
    )
    pack.add_argument("bot", help="bot folder (with bot.py) or a .py file")
    pack.add_argument("--team", required=True, help="your team name")
    pack.add_argument("--out", default=".", help="folder for the .pkl")
    pack.add_argument("--no-validate", action="store_true")
    pack.set_defaults(handler=cmd_pack)

    add_tournament_parser(commands)

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

    sub = organiser(
        "import", "import the .pkl files the form collected", cmd_import
    )
    sub.add_argument("folder", help="folder with the downloaded .pkl files")
    sub.add_argument("--no-validate", action="store_true")

    sub = organiser("submit", "add a bot version", cmd_submit)
    sub.add_argument("team")
    sub.add_argument("source", help="folder, bot.py or git URL")
    sub.add_argument("--no-validate", action="store_true")
    sub.add_argument("--move-timeout", type=float, default=1.0)
    sub.add_argument("--branch", help="branch to use when SOURCE is a git URL")

    sub = organiser("ladder", "run the live ladder", cmd_ladder, play=True)
    sub.add_argument("--deals", type=int, default=200)
    sub.add_argument(
        "--submissions",
        help="folder of <team>/bot.py directories to watch for changes",
    )
    sub.add_argument("--once", action="store_true")
    sub.add_argument("--interval", type=float, default=10.0)
    sub.add_argument(
        "--cycle",
        type=float,
        metavar="SECONDS",
        help="timed mode: every SECONDS, play EVERY pairing again on fresh "
        "cards and pool the results (the results appear once the round is "
        "complete, so a site is redeployed once per cycle). --deals is then "
        "the number of deals per pairing per round",
    )
    sub.add_argument(
        "--teams",
        help="teams file (team + git URL per line): pull each team's repo",
    )
    sub.add_argument(
        "--sync-interval",
        type=float,
        default=60.0,
        help="seconds between pulls of the teams' repositories",
    )
    sub.add_argument("--clone-timeout", type=float, default=90.0)
    _registry_options(sub)

    sub = organiser(
        "sync", "pull each team's bot from its git repository", cmd_sync
    )
    sub.add_argument("--teams", help="teams file")
    _registry_options(sub)
    sub.add_argument("--once", action="store_true")
    sub.add_argument("--interval", type=float, default=60.0)
    sub.add_argument("--move-timeout", type=float, default=1.0)
    sub.add_argument("--clone-timeout", type=float, default=90.0)

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
        "--guide",
        help="markdown for the 'How to submit' page "
        "(default: SUBMITTING.md or README.md in the repository)",
    )
    sub.add_argument(
        "--registry-repo",
        metavar="OWNER/REPO",
        help="show a Register page that opens an issue in this GitHub "
        "repository",
    )
    sub.add_argument(
        "--registrations",
        metavar="CSV_FILE_OR_URL",
        help="team names registered on the website (the registration form's "
        "sheet as a CSV file, or its published-to-the-web CSV address)",
    )
    sub.add_argument(
        "--register-form",
        metavar="URL",
        help="the registration Google Form's prefilled link, ending in "
        "entry.NUMBER= ; turns on the site's Register page",
    )
    sub.add_argument(
        "--no-guide",
        action="store_true",
        help="leave the 'How to submit' page out of the site",
    )
    sub.add_argument(
        "--event-file",
        metavar="FILE",
        help="the Home page text (default: event.json in the repository)",
    )
    sub.add_argument(
        "--no-event",
        action="store_true",
        help="leave the Home page out of the site",
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
