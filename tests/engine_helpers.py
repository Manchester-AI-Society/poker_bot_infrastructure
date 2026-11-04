"""Shared helpers for engine-level tests driven through GameService."""

from __future__ import annotations

from typing import Dict, List, Optional

from game.game_service_core import GameService
from game.match_runtime import MatchRuntime
from game.poker_card import PokerCard

_RANKS = {"A": 1, "T": 10, "J": 11, "Q": 12, "K": 13}
_RANKS.update({str(n): n for n in range(2, 10)})
_SUITS = {"S": "spades", "C": "clubs", "H": "hearts", "D": "diamonds"}


def card(code: str) -> PokerCard:
    return PokerCard(_RANKS[code[0]], _SUITS[code[1]])


def rig(runtime: MatchRuntime, holes: Dict[int, str], board: str) -> None:
    """Overwrites dealt cards so showdown outcomes are deterministic."""
    for seat, codes in holes.items():
        runtime.players[seat].cards = [card(c) for c in codes.split()]
    runtime.engine.board.cards = [card(c) for c in board.split()]


async def new_match(
    stacks: List[int],
    *,
    small_blind: int = 10,
    big_blind: int = 20,
    timeout: int = 3600,
    max_hands: Optional[int] = 1,
) -> tuple[GameService, MatchRuntime]:
    service = GameService()
    runtime = service.create_match(
        player_ids=[f"p{i}" for i in range(len(stacks))],
        starting_stack=max(stacks),
        small_blind=small_blind,
        big_blind=big_blind,
        turn_timeout_seconds=timeout,
        max_hands=max_hands,
        wait_for_players=False,
    )
    for seat, stack in zip(runtime.players, stacks):
        seat.curr_balance = stack
    await service.start_match(runtime.match_id, force=True)
    return service, runtime


async def act(
    service: GameService,
    runtime: MatchRuntime,
    action: str,
    amount: Optional[int] = None,
) -> str:
    """Submits an action for whoever is currently to act."""
    state = service.get_public_state(runtime.match_id)
    player_id = state["current_player_id"]
    await service.submit_action(
        match_id=runtime.match_id,
        player_id=player_id,
        action=action,
        amount=amount,
        turn_id=state["turn_id"],
    )
    return player_id


async def check_down(service: GameService, runtime: MatchRuntime) -> None:
    while runtime.status == "running":
        await act(service, runtime, "check")


def showdown_winnings(runtime: MatchRuntime) -> Dict[str, int]:
    events = [e for e in runtime.action_log if e["type"] == "showdown"]
    assert events, "no showdown was logged"
    return {r["player_id"]: r["winnings"] for r in events[-1]["results"]}


def stacks(runtime: MatchRuntime) -> List[int]:
    return [seat.curr_balance for seat in runtime.players]
