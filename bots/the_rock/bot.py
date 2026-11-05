"""The Rock: waits for a premium hand and then bets it for value.

Folds almost everything, never bluffs, and never pays off big bets without a
strong hand. Very hard to bluff, but the blinds eat into its stack while it
waits, and aggressive opponents who steal the pot every time do well against
it. A useful baseline for "what happens if you are too careful".

Try it:

    python -m arena match bots/the_rock call --deals 200
    python -m arena match bots/the_rock bots/loose_aggressive --deals 300
"""

from __future__ import annotations

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

    best = max(counts.values())
    pairs = sorted((v for v, n in counts.items() if n == 2), reverse=True)
    if best >= 4:
        return 0.98
    if best == 3 and pairs:
        return 0.95
    if max(suits.count(s) for s in set(suits)) >= 5:
        return 0.92
    if best == 3:
        return 0.85
    if len(pairs) >= 2:
        return 0.78
    if len(pairs) == 1 and pairs[0] in hole_ranks:
        return 0.64 if pairs[0] >= max(board_ranks) else 0.48
    return 0.15


def sized_raise(game_state: GameState, fraction: float) -> int:
    low = game_state.min_raise_to or 1
    high = game_state.max_raise_to or low
    extra = int(fraction * (game_state.pot_size + game_state.call_amount))
    target = (game_state.my_bet or 0) + game_state.call_amount + extra
    return max(min(target, high), min(low, high))


class RockBot(PokerBot):
    def act(self, gs: GameState) -> Action:
        can_raise = gs.can_raise or gs.can_bet
        free = gs.call_amount == 0
        bb = gs.big_blind or 20

        if gs.is_preflop:
            strength = preflop_strength(gs.hole_cards)
            if can_raise and strength >= 0.80:
                return Action.raise_to(sized_raise(gs, 1.0))
            if free:
                return Action.call()  # check the big blind option
            # Call a small raise with a good hand, fold the rest.
            if strength >= 0.62 and gs.call_amount <= 4 * bb:
                return Action.call()
            return Action.fold()

        strength = postflop_strength(gs.hole_cards, gs.community_cards)
        if can_raise and strength >= 0.78:
            return Action.raise_to(sized_raise(gs, 0.75))
        if free:
            return Action.call()  # check
        # Only continue against a bet with a real hand.
        return Action.call() if strength >= 0.60 else Action.fold()
