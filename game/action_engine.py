from __future__ import annotations

from typing import Callable, Dict, Optional, Tuple

from .game_domain_models import InvalidActionError
from .match_runtime import MatchRuntime


def legal_actions(runtime: MatchRuntime, actor_index: int) -> list[str]:
    """Returns the legal actions for the acting player."""
    seat = runtime.players[actor_index]
    to_call = max(0, runtime.engine.call_amount - seat.curr_bet_amount)

    actions = ["fold"]
    if to_call == 0:
        actions.append("check")
        if seat.curr_balance > 0:
            actions.append("bet")
    else:
        actions.append("call")

    if seat.curr_balance > to_call and runtime.engine.call_amount > 0:
        actions.append("raise_to")
    return actions


def min_raise_to(runtime: MatchRuntime, actor_index: int) -> int:
    """Calculates the minimum allowed raise target."""
    seat = runtime.players[actor_index]
    to_call = max(0, runtime.engine.call_amount - seat.curr_bet_amount)

    if to_call == 0:
        big_blind = int(runtime.engine.big_blind_amount)
        return max(
            big_blind,
            runtime.engine.call_amount + big_blind,
        )
    return runtime.engine.call_amount + max(
        int(runtime.engine.big_blind_amount),
        runtime.min_raise_size,
    )


def apply_action(
    runtime: MatchRuntime,
    actor_index: int,
    action: str,
    amount: Optional[int],
) -> Tuple[str, Optional[int]]:
    """Validates and applies an action for the acting player."""
    seat = runtime.players[actor_index]
    to_call = max(0, runtime.engine.call_amount - seat.curr_bet_amount)
    legal = legal_actions(runtime, actor_index)

    if action not in legal:
        raise InvalidActionError(
            f"Illegal action '{action}'. Legal actions: {legal}"
        )

    handler = _ACTION_HANDLERS.get(action)
    if handler is None:
        raise InvalidActionError(f"Unsupported action '{action}'")

    emitted_amount = handler(runtime, seat, actor_index, to_call, amount)

    _register_move(runtime, seat.player_id, action, emitted_amount)
    return action, emitted_amount


def _handle_fold(
    runtime: MatchRuntime,
    seat,
    actor_index: int,
    to_call: int,
    amount: Optional[int],
) -> Optional[int]:
    """Applies a fold action for the acting player."""
    seat.fold()
    seat.has_moved = True
    return None


def _handle_check(
    runtime: MatchRuntime,
    seat,
    actor_index: int,
    to_call: int,
    amount: Optional[int],
) -> Optional[int]:
    """Applies a check action for the acting player."""
    if to_call != 0:
        raise InvalidActionError("Cannot check when facing a bet")
    seat.check(runtime.engine.call_amount)
    seat.has_moved = True
    return None


def _handle_call(
    runtime: MatchRuntime,
    seat,
    actor_index: int,
    to_call: int,
    amount: Optional[int],
) -> Optional[int]:
    """Applies a call action for the acting player."""
    if to_call <= 0:
        raise InvalidActionError("Cannot call when no call amount is due")
    if to_call >= seat.curr_balance:
        committed = seat.all_in()
    else:
        committed = seat.call_bet(runtime.engine.call_amount)
    runtime.engine.pot += committed
    seat.has_moved = True
    return committed


def _handle_bet(
    runtime: MatchRuntime,
    seat,
    actor_index: int,
    to_call: int,
    amount: Optional[int],
) -> Optional[int]:
    """Applies a bet action for the acting player."""
    if amount is None:
        raise InvalidActionError("Bet requires an amount")
    if runtime.engine.call_amount != 0:
        raise InvalidActionError("Use raise_to when a bet already exists")
    minimum = int(runtime.engine.big_blind_amount)
    if amount < minimum:
        raise InvalidActionError(f"Bet must be at least {minimum}")

    target_total = min(seat.curr_bet_amount + seat.curr_balance, amount)
    placed = target_total - seat.curr_bet_amount
    if placed <= 0:
        raise InvalidActionError("Bet amount is too small")

    seat.commit_chips(placed)
    runtime.engine.pot += placed
    previous_bet = runtime.engine.call_amount
    runtime.engine.call_amount = seat.curr_bet_amount
    runtime.min_raise_size = max(
        int(runtime.engine.big_blind_amount),
        runtime.engine.call_amount - previous_bet,
    )
    reset_acted_flags_after_aggression(runtime, actor_index)
    return seat.curr_bet_amount


def _handle_raise_to(
    runtime: MatchRuntime,
    seat,
    actor_index: int,
    to_call: int,
    amount: Optional[int],
) -> Optional[int]:
    """Applies a raise-to action for the acting player."""
    if amount is None:
        raise InvalidActionError("raise_to requires an amount")
    minimum = min_raise_to(runtime, actor_index)
    maximum = seat.curr_bet_amount + seat.curr_balance
    if amount < minimum:
        raise InvalidActionError(f"raise_to must be at least {minimum}")
    if amount > maximum:
        raise InvalidActionError(f"raise_to cannot exceed {maximum}")

    commit_amount = amount - seat.curr_bet_amount
    seat.commit_chips(commit_amount)
    runtime.engine.pot += commit_amount
    raise_size = amount - runtime.engine.call_amount
    runtime.engine.call_amount = amount
    runtime.min_raise_size = max(
        int(runtime.engine.big_blind_amount),
        raise_size,
    )
    reset_acted_flags_after_aggression(runtime, actor_index)
    return amount


_ACTION_HANDLERS: Dict[str, Callable[..., Optional[int]]] = {
    "fold": _handle_fold,
    "check": _handle_check,
    "call": _handle_call,
    "bet": _handle_bet,
    "raise_to": _handle_raise_to,
}


def next_eligible_player(
    runtime: MatchRuntime, start_index: int
) -> Optional[int]:
    """Finds the next player who can still act."""
    count = len(runtime.players)
    for offset in range(count):
        index = (start_index + offset) % count
        seat = runtime.players[index]
        if not seat.is_folded and not seat.is_all_in:
            return index
    return None


def remaining_players(runtime: MatchRuntime) -> int:
    """Returns the number of players who have not folded."""
    return sum(1 for seat in runtime.players if not seat.is_folded)


def all_remaining_all_in(runtime: MatchRuntime) -> bool:
    """Returns whether all non-folded players are all-in."""
    active = [seat for seat in runtime.players if not seat.is_folded]
    if len(active) <= 1:
        return False
    return all(seat.is_all_in for seat in active)


def reset_acted_flags_after_aggression(
    runtime: MatchRuntime, aggressor_index: int
) -> None:
    """Resets action flags after a bet or raise."""
    for index, seat in enumerate(runtime.players):
        if seat.is_folded or seat.is_all_in:
            continue
        seat.has_moved = index == aggressor_index


def _register_move(
    runtime: MatchRuntime,
    player_id: str,
    action: str,
    emitted_amount: Optional[int],
) -> None:
    """Appends an action record to the current street registry."""
    move = (player_id, action, emitted_amount or 0)
    street = runtime.engine.curr_street
    registry = getattr(runtime.engine, f"{street}_moves", None)
    if registry is not None:
        registry.append(move)
