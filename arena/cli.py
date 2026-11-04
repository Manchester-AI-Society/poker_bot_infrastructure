"""Command line: ``python -m arena <command>``.

Commands for participants:
    match A B     play a duplicate match locally (the same code path and
                  scoring the competition uses)
    validate BOT  check that a bot loads and plays legally on time
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import List, Optional

from .duel import PairingConfig, PairingResult, play_pairing
from .history import HandWriter
from .specs import contestant_from_spec
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
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    sys.exit(main())
