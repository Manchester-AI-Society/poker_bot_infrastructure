from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Tuple

from .action_engine import (
    all_remaining_all_in,
    legal_actions,
    min_raise_to,
    next_eligible_player,
    remaining_players,
)
from .match_runtime import MatchRuntime
from .showdown_resolver import settle_fold_win, settle_showdown
from .state_projection import build_public_state

LogEventCallback = Callable[[MatchRuntime, str, Dict[str, Any]], None]


def prepare_turn_event(
    runtime: MatchRuntime, log_event: LogEventCallback
) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
    """Builds the next turn event payload for the active player."""
    if runtime.status != "running":
        return None, None

    actor_index = current_actor_index(runtime)
    if actor_index is None:
        return None, None

    seat = runtime.players[actor_index]
    runtime.turn_id += 1

    state = build_public_state(
        runtime,
        seat.player_id,
        actor_index,
    )
    hole_cards = state["players"][actor_index].get("hole_cards", [])
    min_raise = min_raise_to(runtime, actor_index)

    event = {
        "type": "your_turn",
        "match_id": runtime.match_id,
        "turn_id": runtime.turn_id,
        "state": {
            **state,
            "hole_cards": hole_cards,
            "legal_actions": legal_actions(runtime, actor_index),
            "min_raise_to": min_raise,
            "max_raise_to": seat.curr_bet_amount + seat.curr_balance,
        },
    }
    log_event(
        runtime,
        "turn_started",
        {"player_id": seat.player_id, "turn_id": runtime.turn_id},
    )
    return seat.player_id, event


def advance_and_settle_if_ready(
    runtime: MatchRuntime, log_event: LogEventCallback
) -> Optional[Dict[str, Any]]:
    """Advances streets and resolves showdown when rounds are complete."""
    if remaining_players(runtime) == 1:
        showdown = settle_fold_win(runtime)
        log_event(runtime, "showdown", {"results": showdown["results"]})
        return showdown

    while not runtime.engine.round_has_pending_actions():
        if runtime.engine.curr_street == "showdown":
            showdown = settle_showdown(runtime)
            log_event(runtime, "showdown", {"results": showdown["results"]})
            return showdown

        runtime.engine.advance_street()
        log_event(
            runtime,
            "street_advanced",
            {
                "street": runtime.engine.curr_street,
                "board": build_public_state(
                    runtime,
                    None,
                    current_actor_index(runtime),
                )["board"],
            },
        )

        if runtime.engine.curr_street == "showdown":
            showdown = settle_showdown(runtime)
            log_event(runtime, "showdown", {"results": showdown["results"]})
            return showdown

        next_index = next_eligible_player(runtime, runtime.engine.turn_index)
        if next_index is None:
            showdown = settle_showdown(runtime)
            log_event(runtime, "showdown", {"results": showdown["results"]})
            return showdown

        runtime.engine.turn_index = next_index
        if not all_remaining_all_in(runtime):
            break

    return None


def current_actor_index(runtime: MatchRuntime) -> Optional[int]:
    """Returns the current eligible actor index for the runtime."""
    if not runtime.players:
        return None

    current = runtime.engine.turn_index % len(runtime.players)
    seat = runtime.players[current]
    if not seat.is_folded and not seat.is_all_in:
        return current

    next_index = next_eligible_player(runtime, current + 1)
    if next_index is None:
        return None
    runtime.engine.turn_index = next_index
    return next_index


def eliminate_busted_players(
    runtime: MatchRuntime, log_event: LogEventCallback
) -> List[str]:
    """Removes chip-less players from the upcoming hand.

    Eliminated seats are marked folded so every existing eligibility
    and contender check (which keys on ``is_folded``) keeps working
    without special cases.
    """
    eliminated: List[str] = []
    for seat in runtime.players:
        if seat.curr_balance > 0:
            continue
        seat.is_folded = True
        if not seat.is_eliminated:
            seat.is_eliminated = True
            eliminated.append(seat.player_id)
    for player_id in eliminated:
        log_event(
            runtime,
            "player_eliminated",
            {"player_id": player_id},
        )
    return eliminated


def begin_next_hand(
    runtime: MatchRuntime, log_event: LogEventCallback
) -> Tuple[List[Dict[str, Any]], Optional[str], Optional[Dict[str, Any]]]:
    """Starts the next hand and prepares its first turn event.

    Returns (broadcast_events, turn_player_id, turn_event).
    """
    runtime.min_raise_size = int(runtime.engine.big_blind_amount)
    runtime.engine.start_hand()
    # Busted seats are folded AFTER the hand reset (which clears
    # is_folded) so every eligibility and contender check keeps
    # excluding them for the rest of the match.
    eliminated = eliminate_busted_players(runtime, log_event)
    log_event(
        runtime,
        "hand_started",
        {
            "hand_number": runtime.engine.hand_number,
            "dealer_index": runtime.engine.dealer_index,
            "eliminated": eliminated,
        },
    )
    blind_events = build_blind_events(runtime)
    turn_player_id, turn_event = prepare_turn_event(runtime, log_event)
    return blind_events, turn_player_id, turn_event


def resolve_match_progression(
    runtime: MatchRuntime, log_event: LogEventCallback
) -> Tuple[
    Optional[Dict[str, Any]],
    List[Dict[str, Any]],
    Optional[str],
    Optional[Dict[str, Any]],
]:
    """Decides what follows a settled hand: match end or a new deal.

    Returns (match_ended_event, broadcast_events, turn_player_id,
    turn_event). ``match_ended_event`` is set when the match is over;
    otherwise the remaining values describe the next hand's opening.
    """
    contenders = [seat for seat in runtime.players if seat.curr_balance > 0]
    hand_limit = runtime.max_hands is not None and (
        runtime.engine.hand_number >= runtime.max_hands
    )

    if len(contenders) > 1 and not hand_limit:
        broadcasts, turn_player_id, turn_event = begin_next_hand(
            runtime, log_event
        )
        return None, broadcasts, turn_player_id, turn_event

    runtime.status = "finished"
    if len(contenders) == 1:
        runtime.winner_ids = [contenders[0].player_id]
        runtime.end_reason = (
            "hand_limit" if hand_limit else "opponents_eliminated"
        )
    else:
        top_stack = max(seat.curr_balance for seat in contenders)
        runtime.winner_ids = [
            seat.player_id
            for seat in contenders
            if seat.curr_balance == top_stack
        ]
        runtime.end_reason = "hand_limit"

    log_event(
        runtime,
        "match_ended",
        {"reason": runtime.end_reason, "winner_ids": runtime.winner_ids},
    )
    match_ended_event = {
        "type": "match_ended",
        "match_id": runtime.match_id,
        "reason": runtime.end_reason,
        "winner_ids": runtime.winner_ids,
        "results": [
            {
                "player_id": seat.player_id,
                "stack": seat.curr_balance,
            }
            for seat in runtime.players
        ],
    }
    return match_ended_event, [], None, None


def build_blind_events(runtime: MatchRuntime) -> List[Dict[str, Any]]:
    """Builds action events for posted blinds at hand start."""
    if len(runtime.engine.preflop_moves) < 2:
        return []

    small_blind = runtime.engine.preflop_moves[0]
    big_blind = runtime.engine.preflop_moves[1]
    return [
        {
            "type": "action",
            "match_id": runtime.match_id,
            "player_id": small_blind[0],
            "action": "post_small_blind",
            "amount": small_blind[2],
        },
        {
            "type": "action",
            "match_id": runtime.match_id,
            "player_id": big_blind[0],
            "action": "post_big_blind",
            "amount": big_blind[2],
        },
    ]
