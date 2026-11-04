"""Plays single heads-up (or any N-seat) hands in-process.

Uses exactly the rules code the server uses (``game/``): action
validation, betting-round completion, side pots and showdown. Bots are
consulted through :class:`arena.contestant.Contestant`.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any, Dict, List, Sequence

from game.action_engine import apply_action
from game.game_domain_models import InvalidActionError
from game.match_runtime import MatchRuntime
from game.player import Player
from game.poker_card import cards_to_codes
from game.poker_game import PokerGame
from game.runtime_flow import (
    current_actor_index,
    finish_action,
    prepare_turn_event,
)
from game.showdown_resolver import settle_showdown

from .contestant import Contestant, fallback_action

SEAT_IDS = tuple(f"seat{index}" for index in range(9))
MAX_ACTIONS_PER_HAND = 400


@dataclass
class HandRecord:
    """Everything needed to replay and audit one hand."""

    hand_index: int
    deal_seed: int
    seats: List[str]
    stacks: List[int]
    hole_cards: List[List[str]]
    board: List[str]
    small_blind: int
    big_blind: int
    dealer_seat: int
    actions: List[Dict[str, Any]] = field(default_factory=list)
    ended_by: str = ""
    results: List[Dict[str, Any]] = field(default_factory=list)
    net: List[int] = field(default_factory=list)
    faults: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "hand_index": self.hand_index,
            "deal_seed": self.deal_seed,
            "seats": self.seats,
            "stacks": self.stacks,
            "hole_cards": self.hole_cards,
            "board": self.board,
            "small_blind": self.small_blind,
            "big_blind": self.big_blind,
            "dealer_seat": self.dealer_seat,
            "actions": self.actions,
            "ended_by": self.ended_by,
            "results": self.results,
            "net": self.net,
            "faults": self.faults,
        }


def play_hand(
    seats: Sequence[Contestant],
    *,
    deal_seed: int,
    hand_index: int = 0,
    stacks: Sequence[int],
    small_blind: int = 10,
    big_blind: int = 20,
) -> HandRecord:
    """Plays one hand and returns its full record.

    ``seats[i]`` plays seat ``i``. The deck is shuffled from
    ``deal_seed`` alone, so the same seed always deals the same cards
    to the same seats. Chip conservation is asserted at the end.
    """
    if len(seats) != len(stacks):
        raise ValueError("one stack per seat is required")

    players = [
        Player(stack, SEAT_IDS[index]) for index, stack in enumerate(stacks)
    ]
    engine = PokerGame(
        players,
        big_blind_amount=big_blind,
        small_blind_amount=small_blind,
        rng=random.Random(deal_seed),
    )
    engine.hand_number = hand_index
    runtime = MatchRuntime(
        match_id=f"hand-{hand_index}",
        engine=engine,
        turn_timeout_seconds=0,
        event_log_limit=1,
        status="running",
    )
    engine.start_hand()

    record = HandRecord(
        hand_index=hand_index,
        deal_seed=deal_seed,
        seats=[seat.name for seat in seats],
        stacks=list(stacks),
        hole_cards=[cards_to_codes(player.cards) for player in players],
        board=cards_to_codes(engine.board.cards),
        small_blind=small_blind,
        big_blind=big_blind,
        dealer_seat=engine.dealer_index,
    )

    history: List[Dict[str, Any]] = []
    blind_names = ("post_small_blind", "post_big_blind")
    for move, name in zip(engine.preflop_moves[:2], blind_names):
        entry = {
            "player_id": move[0],
            "action": name,
            "amount": move[2],
            "street": "preflop",
        }
        history.append(entry)
        record.actions.append(
            {**entry, "seat": SEAT_IDS.index(move[0]), "fault": None}
        )

    def log_event(_runtime, _kind, _payload) -> None:
        return None

    showdown = None
    for _ in range(MAX_ACTIONS_PER_HAND):
        actor = current_actor_index(runtime)
        if actor is None:
            showdown = settle_showdown(runtime)
            break

        _, event = prepare_turn_event(runtime, log_event)
        state = event["state"]
        decision = seats[actor].decide(state, actor, history)
        street_before = engine.curr_street
        fault = decision.fault

        action = "raise_to" if decision.action == "raise" else decision.action
        try:
            name, emitted = apply_action(
                runtime, actor, action, decision.amount
            )
        except InvalidActionError as exc:
            fault = f"illegal action {decision.action}: {exc}"
            seats[actor].record_fault(fault)
            name, emitted = apply_action(
                runtime,
                actor,
                fallback_action(state["legal_actions"]),
                None,
            )

        entry = {
            "player_id": SEAT_IDS[actor],
            "action": name,
            "amount": emitted,
            "street": street_before,
        }
        history.append(entry)
        record.actions.append({**entry, "seat": actor, "fault": fault})
        if fault:
            record.faults += 1

        showdown = finish_action(runtime, actor, street_before, log_event)
        if showdown is not None:
            break
    else:
        raise RuntimeError("hand did not finish within the action limit")

    record.ended_by = (
        "showdown"
        if any(
            result["hand"] not in ("Won by Fold", "Folded")
            for result in showdown["results"]
        )
        else "fold"
    )
    record.results = showdown["results"]
    record.net = [
        player.curr_balance - stack for player, stack in zip(players, stacks)
    ]
    if sum(record.net) != 0:
        raise RuntimeError(f"chips not conserved: net={record.net}")
    return record
