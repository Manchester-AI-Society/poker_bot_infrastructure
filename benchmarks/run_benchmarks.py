from __future__ import annotations

import argparse
import asyncio
import gc
import json
import random
import statistics
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from time import perf_counter
from typing import Any, Awaitable, Callable, Dict, Iterable, List, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from game.action_engine import legal_actions, min_raise_to
from game.game_service_core import GameService
from game.match_runtime import MatchRuntime
from game.player import Player
from game.poker_game import PokerGame
from game.poker_hand_evaluator import evaluate_best_hand
from game.runtime_flow import current_actor_index
from game.state_projection import build_public_state
from server.websocket_connection_manager import ConnectionManager

SyncBenchFn = Callable[[], None]
AsyncBenchFn = Callable[[], Awaitable[None]]


@dataclass
class BenchmarkResult:
    name: str
    iterations: int
    total_seconds: float
    avg_milliseconds: float
    ops_per_second: float
    notes: Dict[str, Any] = field(default_factory=dict)


def _time_sync(
    *,
    name: str,
    iterations: int,
    warmup: int,
    fn: SyncBenchFn,
    notes: Optional[Dict[str, Any]] = None,
) -> BenchmarkResult:
    for _ in range(warmup):
        fn()

    gc_was_enabled = gc.isenabled()
    gc.disable()
    try:
        started_at = perf_counter()
        for _ in range(iterations):
            fn()
        total_seconds = perf_counter() - started_at
    finally:
        if gc_was_enabled:
            gc.enable()

    avg_ms = (total_seconds / iterations) * 1000
    ops_per_second = iterations / total_seconds if total_seconds > 0 else 0.0
    return BenchmarkResult(
        name=name,
        iterations=iterations,
        total_seconds=total_seconds,
        avg_milliseconds=avg_ms,
        ops_per_second=ops_per_second,
        notes=notes or {},
    )


async def _time_async(
    *,
    name: str,
    iterations: int,
    warmup: int,
    fn: AsyncBenchFn,
    notes: Optional[Dict[str, Any]] = None,
) -> BenchmarkResult:
    for _ in range(warmup):
        await fn()

    gc_was_enabled = gc.isenabled()
    gc.disable()
    try:
        started_at = perf_counter()
        for _ in range(iterations):
            await fn()
        total_seconds = perf_counter() - started_at
    finally:
        if gc_was_enabled:
            gc.enable()

    avg_ms = (total_seconds / iterations) * 1000
    ops_per_second = iterations / total_seconds if total_seconds > 0 else 0.0
    return BenchmarkResult(
        name=name,
        iterations=iterations,
        total_seconds=total_seconds,
        avg_milliseconds=avg_ms,
        ops_per_second=ops_per_second,
        notes=notes or {},
    )


def _create_runtime(
    player_count: int = 6, starting_stack: int = 1000
) -> MatchRuntime:
    seats = [
        Player(curr_balance=starting_stack, player_id=f"p{idx}")
        for idx in range(player_count)
    ]
    engine = PokerGame(
        players=seats,
        big_blind_amount=20,
        small_blind_amount=10,
    )
    engine.start_hand()
    return MatchRuntime(
        match_id="bench_runtime",
        engine=engine,
        turn_timeout_seconds=15,
        event_log_limit=50000,
        status="running",
    )


def _deck_codes() -> List[str]:
    ranks = "23456789TJQKA"
    suits = "SHDC"
    return [f"{rank}{suit}" for rank in ranks for suit in suits]


def _sample_hands(seed: int, sample_size: int) -> List[List[str]]:
    rng = random.Random(seed)
    deck = _deck_codes()
    return [rng.sample(deck, 7) for _ in range(sample_size)]


class _FakeWebSocket:
    def __init__(self) -> None:
        self.messages_sent = 0

    async def accept(self) -> None:
        return None

    async def send_json(self, _payload: Dict[str, Any]) -> None:
        self.messages_sent += 1


async def _benchmark_service_lifecycle_once(
    service: GameService, player_ids: List[str]
) -> int:
    runtime = service.create_match(
        player_ids=player_ids,
        turn_timeout_seconds=120,
        event_log_limit=3000,
        max_hands=1,
        wait_for_players=False,
    )
    await service.start_match(runtime.match_id, force=True)
    actions_taken = 0

    while runtime.status == "running":
        base_state = service.get_public_state(runtime.match_id)
        player_id = base_state.get("current_player_id")
        if not player_id:
            break

        viewer_state = service.get_public_state(
            runtime.match_id, viewer_id=player_id
        )
        legal_actions: List[str] = viewer_state.get("legal_actions", [])

        action = "fold"
        if "check" in legal_actions:
            action = "check"
        elif "call" in legal_actions:
            action = "call"

        await service.submit_action(
            match_id=runtime.match_id,
            player_id=player_id,
            action=action,
            amount=None,
            turn_id=base_state.get("turn_id"),
        )
        actions_taken += 1

    return actions_taken


def benchmark_action_engine_rules(
    iterations: int, warmup: int
) -> BenchmarkResult:
    runtime = _create_runtime()
    actor_index = runtime.engine.turn_index

    def _run() -> None:
        legal_actions(runtime, actor_index)
        min_raise_to(runtime, actor_index)

    return _time_sync(
        name="action_engine_rules",
        iterations=iterations,
        warmup=warmup,
        fn=_run,
        notes={"player_count": len(runtime.players)},
    )


def benchmark_state_projection(
    iterations: int, warmup: int
) -> BenchmarkResult:
    runtime = _create_runtime()
    actor_index = current_actor_index(runtime)
    if actor_index is None:
        viewer_id = None
    else:
        viewer_id = runtime.players[actor_index].player_id

    def _run() -> None:
        build_public_state(runtime, viewer_id, actor_index)

    return _time_sync(
        name="state_projection_public",
        iterations=iterations,
        warmup=warmup,
        fn=_run,
        notes={"player_count": len(runtime.players)},
    )


def benchmark_showdown_evaluator(
    iterations: int, warmup: int, seed: int
) -> BenchmarkResult:
    hands = _sample_hands(seed=seed, sample_size=256)
    hand_count = len(hands)
    index = 0

    def _run() -> None:
        nonlocal index
        evaluate_best_hand(hands[index % hand_count])
        index += 1

    return _time_sync(
        name="showdown_evaluator_7card",
        iterations=iterations,
        warmup=warmup,
        fn=_run,
        notes={"hand_sample_size": hand_count},
    )


def benchmark_log_pagination(
    iterations: int,
    warmup: int,
    log_events: int,
) -> BenchmarkResult:
    service = GameService()
    runtime = service.create_match(
        player_ids=["p1", "p2", "p3", "p4"],
        event_log_limit=max(log_events + 100, 1000),
    )

    for event_id in range(log_events):
        runtime.action_log.append(
            {
                "timestamp": float(event_id),
                "type": "action",
                "event_id": event_id,
                "player_id": f"p{event_id % 4}",
            }
        )

    page_size = 200
    middle_offset = max(0, log_events // 2)

    def _run() -> None:
        service.get_logs_page(
            runtime.match_id,
            offset=middle_offset,
            limit=page_size,
        )

    return _time_sync(
        name="event_log_pagination",
        iterations=iterations,
        warmup=warmup,
        fn=_run,
        notes={
            "log_events": log_events,
            "page_size": page_size,
            "offset": middle_offset,
        },
    )


async def benchmark_service_lifecycle(
    iterations: int,
    warmup: int,
) -> BenchmarkResult:
    service = GameService()

    async def _noop_broadcast(
        _player_ids: Iterable[str], _payload: Dict[str, Any]
    ) -> None:
        return None

    async def _noop_direct(_player_id: str, _payload: Dict[str, Any]) -> None:
        return None

    service.set_event_handlers(
        broadcast_cb=_noop_broadcast,
        direct_cb=_noop_direct,
    )

    player_ids = ["p1", "p2", "p3", "p4", "p5", "p6"]

    action_counts: List[int] = []

    async def _run() -> None:
        action_count = await _benchmark_service_lifecycle_once(
            service, player_ids
        )
        action_counts.append(action_count)

    result = await _time_async(
        name="service_match_lifecycle",
        iterations=iterations,
        warmup=warmup,
        fn=_run,
    )
    if action_counts:
        result.notes["avg_actions_per_match"] = round(
            statistics.fmean(action_counts), 2
        )
        result.notes["max_actions_in_match"] = max(action_counts)
    return result


async def benchmark_connection_broadcast(
    iterations: int,
    warmup: int,
    player_count: int,
) -> BenchmarkResult:
    manager = ConnectionManager()
    player_ids = [f"ws_{idx}" for idx in range(player_count)]

    for player_id in player_ids:
        await manager.connect(player_id, _FakeWebSocket())

    payload = {
        "type": "bench_event",
        "match_id": "bench",
        "value": 123,
        "message": "benchmark_payload",
    }

    async def _run() -> None:
        await manager.broadcast_to_players(player_ids, payload)

    result = await _time_async(
        name="connection_broadcast",
        iterations=iterations,
        warmup=warmup,
        fn=_run,
        notes={"player_count": player_count},
    )

    for player_id in player_ids:
        await manager.disconnect(player_id)

    return result


def _print_results(results: List[BenchmarkResult]) -> None:
    print()
    print(
        "Scenario                    Iterations   Total(s)   Avg(ms)    Ops/s"
    )
    print(
        "------------------------   ----------   --------   -------    -------"
    )
    for item in results:
        print(
            f"{item.name:<26}   "
            f"{item.iterations:>10}   "
            f"{item.total_seconds:>8.4f}   "
            f"{item.avg_milliseconds:>7.4f}    "
            f"{item.ops_per_second:>7.2f}"
        )

    print()
    print("Notes")
    print("-----")
    for item in results:
        if not item.notes:
            continue
        rendered_notes = ", ".join(
            f"{key}={value}" for key, value in item.notes.items()
        )
        print(f"- {item.name}: {rendered_notes}")


def _write_json_results(
    results: List[BenchmarkResult], output_path: Path
) -> None:
    payload = {
        "results": [asdict(item) for item in results],
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


async def _run_async_scenarios(
    args: argparse.Namespace,
) -> List[BenchmarkResult]:
    enabled = set(args.only or [])

    def _selected(name: str) -> bool:
        return not enabled or name in enabled

    results: List[BenchmarkResult] = []

    if _selected("service_match_lifecycle"):
        results.append(
            await benchmark_service_lifecycle(
                iterations=args.lifecycle_iterations,
                warmup=args.async_warmup,
            )
        )

    if _selected("connection_broadcast"):
        results.append(
            await benchmark_connection_broadcast(
                iterations=args.broadcast_iterations,
                warmup=args.async_warmup,
                player_count=args.broadcast_player_count,
            )
        )

    return results


def _run_sync_scenarios(args: argparse.Namespace) -> List[BenchmarkResult]:
    enabled = set(args.only or [])

    def _selected(name: str) -> bool:
        return not enabled or name in enabled

    results: List[BenchmarkResult] = []

    if _selected("action_engine_rules"):
        results.append(
            benchmark_action_engine_rules(
                iterations=args.sync_iterations,
                warmup=args.sync_warmup,
            )
        )

    if _selected("state_projection_public"):
        results.append(
            benchmark_state_projection(
                iterations=args.sync_iterations,
                warmup=args.sync_warmup,
            )
        )

    if _selected("showdown_evaluator_7card"):
        results.append(
            benchmark_showdown_evaluator(
                iterations=args.evaluator_iterations,
                warmup=args.sync_warmup,
                seed=args.seed,
            )
        )

    if _selected("event_log_pagination"):
        results.append(
            benchmark_log_pagination(
                iterations=args.pagination_iterations,
                warmup=args.sync_warmup,
                log_events=args.log_events,
            )
        )

    return results


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run focused benchmarks for poker server hot paths."
    )
    parser.add_argument(
        "--only",
        nargs="+",
        choices=[
            "action_engine_rules",
            "state_projection_public",
            "showdown_evaluator_7card",
            "event_log_pagination",
            "service_match_lifecycle",
            "connection_broadcast",
        ],
        help="Run only selected scenarios.",
    )
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--sync-iterations", type=int, default=50000)
    parser.add_argument("--evaluator-iterations", type=int, default=25000)
    parser.add_argument("--pagination-iterations", type=int, default=5000)
    parser.add_argument("--lifecycle-iterations", type=int, default=80)
    parser.add_argument("--broadcast-iterations", type=int, default=1500)
    parser.add_argument("--broadcast-player-count", type=int, default=40)
    parser.add_argument("--log-events", type=int, default=50000)
    parser.add_argument("--sync-warmup", type=int, default=500)
    parser.add_argument("--async-warmup", type=int, default=20)
    parser.add_argument("--json-output", type=Path)
    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    sync_results = _run_sync_scenarios(args)
    async_results = asyncio.run(_run_async_scenarios(args))

    results = sync_results + async_results
    if not results:
        parser.error("No benchmark scenarios were selected")

    _print_results(results)

    if args.json_output:
        _write_json_results(results, args.json_output)
        print()
        print(f"Saved JSON results to: {args.json_output}")


if __name__ == "__main__":
    main()
