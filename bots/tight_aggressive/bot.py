"""Tight-aggressive (TAG): plays fewer hands, but plays them hard.

The classic winning style against weak opponents. Preflop it raises its good
hands and folds the junk; after the flop it bets strong hands for value,
sometimes continuation-bets as a bluff, and only calls when the price is
right. Position matters heads-up: the button (small blind) acts last after
the flop, so it opens a little wider there.

Try it:

    python -m arena match bots/tight_aggressive call --deals 200
    python -m arena match bots/tight_aggressive bots/starter --deals 300
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
    """Rough 0..1 score: pairs and high cards, a bonus for suited/connected."""
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
    """Rough 0..1 score from the made hand and a flush draw."""
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
        return 0.30  # the board's own pair: everyone has it
    if most_suited == 4:
        return 0.38
    return 0.12 + max(hole_ranks) / 100


def sized_raise(game_state: GameState, fraction: float) -> int:
    """A raise that puts in `fraction` of the pot on top of calling."""
    low = game_state.min_raise_to or 1
    high = game_state.max_raise_to or low
    extra = int(fraction * (game_state.pot_size + game_state.call_amount))
    target = (game_state.my_bet or 0) + game_state.call_amount + extra
    return max(min(target, high), min(low, high))


class TightAggressiveBot(PokerBot):
    def __init__(self) -> None:
        self.rng = random.Random(7)

    def act(self, game_state: GameState) -> Action:
        hole = game_state.hole_cards
        if game_state.is_preflop:
            return self._preflop(game_state, preflop_strength(hole))
        strength = postflop_strength(hole, game_state.community_cards)
        return self._postflop(game_state, strength)

    # -- preflop --------------------------------------------------------

    def _preflop(self, gs: GameState, strength: float) -> Action:
        bb = gs.big_blind or 20
        can_raise = gs.can_raise or gs.can_bet
        # The button acts last after the flop, so it plays a bit wider.
        open_at = 0.50 if gs.is_dealer else 0.58

        if gs.call_amount <= bb:  # nobody has raised yet
            if can_raise and strength >= open_at:
                return Action.raise_to(
                    max(
                        gs.min_raise_to or 0,
                        min(3 * bb, gs.max_raise_to or 3 * bb),
                    )
                )
            if gs.call_amount == 0:
                return Action.call()  # free option
            return Action.call() if strength >= 0.36 else Action.fold()

        # Facing a raise: re-raise the best hands, call at the right price.
        if can_raise and strength >= 0.86:
            return Action.raise_to(sized_raise(gs, 0.9))
        price = gs.call_amount / (gs.pot_size + gs.call_amount)
        return Action.call() if strength >= price + 0.14 else Action.fold()

    # -- postflop -------------------------------------------------------

    def _postflop(self, gs: GameState, strength: float) -> Action:
        can_raise = gs.can_raise or gs.can_bet
        free = gs.call_amount == 0

        if strength >= 0.78:  # strong: bet or raise for value
            if can_raise:
                return Action.raise_to(sized_raise(gs, 0.7))
            return Action.call()

        if free:
            if can_raise and strength >= 0.55:
                return Action.raise_to(sized_raise(gs, 0.45))  # thin value
            # A small continuation bet now and then, mostly on the flop.
            if can_raise and gs.is_flop and self.rng.random() < 0.30:
                return Action.raise_to(sized_raise(gs, 0.5))
            return Action.call()  # check

        price = gs.call_amount / (gs.pot_size + gs.call_amount)
        if strength >= price + 0.12:
            return Action.call()
        return Action.fold()
