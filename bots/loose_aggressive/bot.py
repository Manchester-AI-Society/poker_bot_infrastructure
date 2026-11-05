"""Loose-aggressive (LAG): plays many hands and keeps up the pressure.

It raises most hands preflop, re-raises often, and keeps betting on later
streets whether or not it has a made hand, so opponents have to make hard
decisions. It folds to a big bet only when it has nothing at all. Strong
against opponents who fold too much; costly against ones who call down.

Try it:

    python -m arena match bots/loose_aggressive call --deals 200
    python -m arena match bots/loose_aggressive bots/the_rock --deals 300
"""

from __future__ import annotations

import random
from typing import Sequence

from player_sdk.bot_interface import PokerBot
from player_sdk.models import Action, GameState

RANKS = "23456789TJQKA"


def _rank(card: str) -> int:
    return RANKS.index(card[0]) + 2


def preflop_strength(hole: Sequence[str]) -> float:
    high, low = sorted((_rank(hole[0]), _rank(hole[1])), reverse=True)
    if high == low:
        return 0.50 + high / 28
    score = (high + low) / 40
    if hole[0][1] == hole[1][1]:
        score += 0.06
    if high - low <= 2:
        score += 0.04
    return min(score, 0.95)


def postflop_strength(hole: Sequence[str], board: Sequence[str]) -> float:
    cards = list(hole) + list(board)
    ranks = [_rank(card) for card in cards]
    counts = {value: ranks.count(value) for value in set(ranks)}
    hole_ranks = {_rank(card) for card in hole}
    board_ranks = [_rank(card) for card in board]
    suits = [card[1] for card in cards]
    most_suited = max(suits.count(s) for s in set(suits))

    best = max(counts.values())
    pairs = sorted((v for v, n in counts.items() if n == 2), reverse=True)
    if best >= 4:
        return 0.98
    if best == 3 and pairs:
        return 0.95
    if most_suited >= 5:
        return 0.92
    if best == 3:
        return 0.85
    if len(pairs) >= 2:
        return 0.78
    if len(pairs) == 1:
        if pairs[0] in hole_ranks:
            return 0.64 if pairs[0] >= max(board_ranks) else 0.50
        return 0.30
    if most_suited == 4:
        return 0.40
    return 0.12 + max(hole_ranks) / 100


def sized_raise(game_state: GameState, fraction: float) -> int:
    low = game_state.min_raise_to or 1
    high = game_state.max_raise_to or low
    extra = int(fraction * (game_state.pot_size + game_state.call_amount))
    target = (game_state.my_bet or 0) + game_state.call_amount + extra
    return max(min(target, high), min(low, high))


class LooseAggressiveBot(PokerBot):
    def __init__(self) -> None:
        self.rng = random.Random(11)

    def act(self, gs: GameState) -> Action:
        hole = gs.hole_cards
        can_raise = gs.can_raise or gs.can_bet
        bb = gs.big_blind or 20

        if gs.is_preflop:
            strength = preflop_strength(hole)
            if gs.call_amount <= bb:
                if can_raise and (
                    strength >= 0.30 or self.rng.random() < 0.25
                ):
                    return Action.raise_to(sized_raise(gs, 1.0))
                return Action.call()
            # Facing a raise: fight back with a wide range.
            if can_raise and strength >= 0.50:
                return Action.raise_to(sized_raise(gs, 0.9))
            price = gs.call_amount / (gs.pot_size + gs.call_amount)
            return Action.call() if strength >= price - 0.05 else Action.fold()

        strength = postflop_strength(hole, gs.community_cards)
        bet_before = self._i_have_bet_this_hand(gs)

        if gs.call_amount == 0:
            # Bet any decent hand, bluff often, and keep firing if we started.
            bluff = 0.55 if bet_before else 0.40
            if can_raise and (strength >= 0.40 or self.rng.random() < bluff):
                return Action.raise_to(sized_raise(gs, 0.65))
            return Action.call()

        # Facing a bet.
        if can_raise and strength >= 0.80:
            return Action.raise_to(sized_raise(gs, 0.8))
        price = gs.call_amount / (gs.pot_size + gs.call_amount)
        if strength >= price - 0.02:
            return Action.call()
        # Occasionally raise as a bluff instead of folding.
        if can_raise and self.rng.random() < 0.08:
            return Action.raise_to(sized_raise(gs, 0.8))
        return Action.fold()

    @staticmethod
    def _i_have_bet_this_hand(gs: GameState) -> bool:
        me = gs.my_player_id
        return any(
            record.player_id == me
            and record.action in ("bet", "raise_to", "raise")
            for record in gs.action_history
        )
