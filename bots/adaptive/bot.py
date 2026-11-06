"""Adaptive: learns how the opponent plays and exploits it.

Your bot's process stays alive across many hands, so it can keep statistics on
`self`. This bot watches two things about the opponent:

* how often they FOLD when it bets (a "folder" gives up easily, so bluff more);
* how often their actions are bets/raises rather than calls (an "aggressor"
  bets with weak hands too, so call down lighter and do not bluff into them).

Until it has seen enough hands it plays a plain tight-aggressive style. It is
restarted for the second half of a match, so it relearns from scratch.

Try it:

    python -m arena match bots/adaptive call --deals 200
    python -m arena match bots/adaptive bots/loose_aggressive --deals 300
"""

from __future__ import annotations

import random
from typing import Sequence

from player_sdk.bot_interface import PokerBot
from player_sdk.models import GameState, Response

RANKS = "23456789TJQKA"
AGGRESSIVE = ("bet", "raise_to", "raise")
MIN_SAMPLES = 12  # opportunities to observe before trusting a statistic


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
        return 0.38
    return 0.12 + max(hole_ranks) / 100


def sized_raise(game_state: GameState, fraction: float) -> int:
    low = game_state.min_raise_to or 1
    high = game_state.max_raise_to or low
    extra = int(fraction * (game_state.pot_size + game_state.call_amount))
    target = (game_state.my_bet or 0) + game_state.call_amount + extra
    return max(min(target, high), min(low, high))


class AdaptiveBot(PokerBot):
    def __init__(self) -> None:
        self.rng = random.Random(99)
        self.faced = 0  # our bets the opponent had to answer
        self.folded = 0  # ... and how many times they folded
        self.aggressive = 0  # opponent bets and raises seen
        self.passive = 0  # opponent calls seen
        self._seen = 0  # how much of this hand's history is already counted
        self._hole = None

    # -- learning -------------------------------------------------------

    def _learn(self, gs: GameState) -> None:
        history = gs.action_history
        if gs.hole_cards != self._hole or len(history) < self._seen:
            self._hole, self._seen = gs.hole_cards, 0  # a new hand
        me = gs.my_player_id
        for index in range(self._seen, len(history)):
            record = history[index]
            if record.player_id == me:
                continue
            before = history[index - 1] if index else None
            answering_my_bet = (
                before is not None
                and before.player_id == me
                and before.action in AGGRESSIVE
            )
            if record.action in AGGRESSIVE:
                self.aggressive += 1
            elif record.action == "call":
                self.passive += 1
            if answering_my_bet and record.action in (
                "fold",
                "call",
                *AGGRESSIVE,
            ):
                self.faced += 1
                self.folded += record.action == "fold"
        self._seen = len(history)

    @property
    def fold_rate(self) -> float:
        return self.folded / self.faced if self.faced >= MIN_SAMPLES else 0.40

    @property
    def aggression(self) -> float:
        total = self.aggressive + self.passive
        return self.aggressive / total if total >= MIN_SAMPLES else 0.40

    # -- decisions ------------------------------------------------------

    def act(self, gs: GameState) -> Response:
        self._learn(gs)
        can_raise = gs.can_raise or gs.can_bet
        bb = gs.big_blind or 20
        folder = self.fold_rate >= 0.55
        maniac = self.aggression >= 0.55
        passive = self.aggression <= 0.25

        if gs.is_preflop:
            strength = preflop_strength(gs.hole_cards)
            open_at = 0.38 if folder else (0.60 if maniac else 0.50)
            if gs.call_amount <= bb:
                if can_raise and strength >= open_at:
                    return Response.raise_to(sized_raise(gs, 1.0))
                return (
                    Response.call()
                    if (gs.call_amount == 0 or strength >= 0.34)
                    else Response.fold()
                )
            if can_raise and strength >= 0.84:
                return Response.raise_to(sized_raise(gs, 0.9))
            price = gs.call_amount / (gs.pot_size + gs.call_amount)
            margin = 0.04 if maniac else 0.14
            return (
                Response.call()
                if strength >= price + margin
                else Response.fold()
            )

        strength = postflop_strength(gs.hole_cards, gs.community_cards)
        if gs.call_amount == 0:
            if can_raise and strength >= (0.45 if passive else 0.62):
                return Response.raise_to(sized_raise(gs, 0.6))
            # Against a folder, bet with nothing: they give up anyway.
            if can_raise and folder and self.rng.random() < 0.55:
                return Response.raise_to(sized_raise(gs, 0.5))
            return Response.call()

        if can_raise and strength >= 0.80:
            return Response.raise_to(sized_raise(gs, 0.8))
        price = gs.call_amount / (gs.pot_size + gs.call_amount)
        if maniac:
            margin = -0.05  # they bet wide, so call down lighter
        elif passive:
            margin = 0.22  # a passive player betting usually has it
        else:
            margin = 0.10
        return (
            Response.call() if strength >= price + margin else Response.fold()
        )
