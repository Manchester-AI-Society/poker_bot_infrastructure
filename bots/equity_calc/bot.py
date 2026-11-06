"""Equity calculator: decide by simulating the hand, not by rules of thumb.

On every decision it deals out the unknown cards at random many times and
counts how often its hand wins against a random opponent hand (its
"equity"). Then it is pure arithmetic: bet when equity is high, call when
equity beats the price the pot offers, fold otherwise. It carries its own
small 7-card hand evaluator, because a bot folder must be self-contained.

Its weakness is the assumption that the opponent holds a random hand; a
player who only bets with strong hands is stronger than the simulation thinks.
Simulation is also the main thing on the clock: it uses about 100 samples per
decision to stay well inside the time budget.

Try it:

    python -m arena match bots/equity_calc call --deals 200
    python -m arena match bots/equity_calc bots/tight_aggressive --deals 300
"""

from __future__ import annotations

import random
from collections import Counter
from typing import Dict, List, Sequence, Tuple

from player_sdk.bot_interface import PokerBot
from player_sdk.models import GameState, Response

RANKS = "23456789TJQKA"
SUITS = "SHDC"
VALUE = {rank: index + 2 for index, rank in enumerate(RANKS)}
FULL_DECK = [rank + suit for rank in RANKS for suit in SUITS]
Card = Tuple[int, str]


def parse(codes: Sequence[str]) -> List[Card]:
    return [(VALUE[code[0]], code[1]) for code in codes]


def straight_high(ranks: set) -> int:
    """High card of the best straight in `ranks`, or 0 (ace plays low too)."""
    ranks = set(ranks)
    if 14 in ranks:
        ranks.add(1)
    for high in range(14, 4, -1):
        if all((high - step) in ranks for step in range(5)):
            return high
    return 0


def hand_value(cards: Sequence[Card]) -> tuple:
    """Comparable value of the best five-card hand in 5 to 7 cards.

    Bigger tuples win. First item is the category (8 straight flush ...
    0 high card), the rest break ties.
    """
    ranks = [rank for rank, _ in cards]
    by_rank = Counter(ranks)
    by_suit: Dict[str, List[int]] = {}
    for rank, suit in cards:
        by_suit.setdefault(suit, []).append(rank)
    flush = next(
        (sorted(v, reverse=True) for v in by_suit.values() if len(v) >= 5),
        None,
    )
    if flush:
        top = straight_high(set(flush))
        if top:
            return (8, top)
    groups = sorted(
        by_rank.items(), key=lambda kv: (kv[1], kv[0]), reverse=True
    )
    top_rank, top_count = groups[0]
    if top_count == 4:
        return (7, top_rank, max(r for r in ranks if r != top_rank))
    if top_count == 3 and len(groups) > 1 and groups[1][1] >= 2:
        return (6, top_rank, groups[1][0])
    if flush:
        return (5, *flush[:5])
    top = straight_high(set(ranks))
    if top:
        return (4, top)
    if top_count == 3:
        kickers = sorted((r for r in ranks if r != top_rank), reverse=True)
        return (3, top_rank, *kickers[:2])
    if top_count == 2 and len(groups) > 1 and groups[1][1] == 2:
        high_pair, low_pair = groups[0][0], groups[1][0]
        kicker = max(r for r in ranks if r not in (high_pair, low_pair))
        return (2, high_pair, low_pair, kicker)
    if top_count == 2:
        kickers = sorted((r for r in ranks if r != top_rank), reverse=True)
        return (1, top_rank, *kickers[:3])
    return (0, *sorted(ranks, reverse=True)[:5])


def sized_raise(game_state: GameState, fraction: float) -> int:
    low = game_state.min_raise_to or 1
    high = game_state.max_raise_to or low
    extra = int(fraction * (game_state.pot_size + game_state.call_amount))
    target = (game_state.my_bet or 0) + game_state.call_amount + extra
    return max(min(target, high), min(low, high))


class EquityBot(PokerBot):
    SAMPLES = 100

    def __init__(self) -> None:
        self.rng = random.Random(2024)

    def equity(self, hole: Sequence[str], board: Sequence[str]) -> float:
        """Chance (0..1) to win at showdown against one random hand."""
        known = set(hole) | set(board)
        deck = [card for card in FULL_DECK if card not in known]
        mine = parse(hole)
        shown = parse(board)
        missing = 5 - len(shown)
        score = 0.0
        for _ in range(self.SAMPLES):
            draw = self.rng.sample(deck, 2 + missing)
            runout = shown + parse(draw[2:])
            ours = hand_value(mine + runout)
            theirs = hand_value(parse(draw[:2]) + runout)
            score += 1.0 if ours > theirs else 0.5 if ours == theirs else 0.0
        return score / self.SAMPLES

    def act(self, gs: GameState) -> Response:
        equity = self.equity(gs.hole_cards, gs.community_cards)
        can_raise = gs.can_raise or gs.can_bet
        bb = gs.big_blind or 20

        if gs.call_amount == 0:  # nothing to pay: bet if we are ahead
            if can_raise and equity >= 0.70:
                return Response.raise_to(sized_raise(gs, 0.75))
            if can_raise and equity >= 0.58:
                return Response.raise_to(sized_raise(gs, 0.45))
            return Response.call()  # check

        if gs.is_preflop and gs.call_amount <= bb:
            # Blind versus blind: open-raise anything better than a coin flip.
            if can_raise and equity >= 0.55:
                return Response.raise_to(
                    max(
                        gs.min_raise_to or 0,
                        min(3 * bb, gs.max_raise_to or 3 * bb),
                    )
                )
            return Response.call() if equity >= 0.42 else Response.fold()

        if can_raise and equity >= 0.78:
            return Response.raise_to(sized_raise(gs, 0.8))
        price = gs.call_amount / (gs.pot_size + gs.call_amount)
        # Equity vs a RANDOM hand overstates our chances against a bettor,
        # so ask for a margin over the pure pot odds.
        return Response.call() if equity >= price + 0.08 else Response.fold()
