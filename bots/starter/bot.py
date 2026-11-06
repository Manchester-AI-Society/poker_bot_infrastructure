"""Starter bot: copy this folder, rename it, and make it better.

How a bot works
---------------
* Your file must define exactly ONE subclass of ``PokerBot``.
* ``act(game_state)`` is called each time it is your turn and must
  return ``Response.fold()``, ``Response.call()`` (this checks when nothing
  is owed) or ``Response.raise_to(total)`` (a bet or raise; ``total`` is
  the TOTAL you want to have in this betting round, between
  ``game_state.min_raise_to`` and ``game_state.max_raise_to``).
* Do heavy set-up (loading files, building tables) at import time or in
  ``__init__``; only ``act`` is on the clock (default limit: 1 second
  per move). Anything you ``print`` goes to your private log, not to the
  opponent.
* Your bot process stays alive for a whole run of hands, so you may keep
  state on ``self`` (e.g. opponent statistics). It is restarted fresh for
  each half of a match, so do not rely on memory across halves.

Test it locally:

    python -m arena match bots/starter @call --deals 100
    python -m arena match bots/starter bots/starter --deals 100

What the starter does: a deliberately simple "tight and honest" policy.
It raises strong hands, calls when the price is right and otherwise
folds or checks. Beat it.
"""

from __future__ import annotations

from typing import Sequence

from player_sdk.bot_interface import PokerBot
from player_sdk.models import GameState, Response

RANKS = "23456789TJQKA"


def _rank(card: str) -> int:
    """2..14 for a card code such as 'AS' or 'TD'."""
    return RANKS.index(card[0]) + 2


def preflop_strength(hole: Sequence[str]) -> float:
    """Rough 0..1 score for two hole cards (pairs and high cards)."""
    high, low = sorted((_rank(hole[0]), _rank(hole[1])), reverse=True)
    if high == low:
        return 0.50 + high / 28  # 22 -> 0.57 ... AA -> 1.0
    score = (high + low) / 40  # AKo -> 0.70, 72o -> 0.23
    if hole[0][1] == hole[1][1]:
        score += 0.06  # suited
    if high - low <= 2:
        score += 0.04  # connected
    return min(score, 0.95)


def postflop_strength(hole: Sequence[str], board: Sequence[str]) -> float:
    """Rough 0..1 score from the made hand and a flush draw."""
    ranks = [_rank(card) for card in list(hole) + list(board)]
    counts = {value: ranks.count(value) for value in set(ranks)}
    hole_ranks = {_rank(card) for card in hole}
    board_ranks = [_rank(card) for card in board]

    best = max(counts.values())
    pairs = sorted((v for v, n in counts.items() if n == 2), reverse=True)
    if best >= 4:
        return 0.98
    if best == 3 and len(pairs) >= 1:
        return 0.95  # full house
    suits = [card[1] for card in list(hole) + list(board)]
    if max(suits.count(s) for s in set(suits)) >= 5:
        return 0.92  # flush
    if best == 3:
        return 0.85
    if len(pairs) >= 2:
        return 0.78
    if len(pairs) == 1:
        if pairs[0] in hole_ranks:
            top_pair = pairs[0] >= max(board_ranks)
            return 0.62 if top_pair else 0.50
        return 0.35  # the board's own pair: everyone has it
    flush_draw = max(suits.count(s) for s in set(suits)) == 4
    return 0.38 if flush_draw else 0.15 + max(hole_ranks) / 100


class StarterBot(PokerBot):
    def act(self, game_state: GameState) -> Response:
        hole = game_state.hole_cards
        board = game_state.community_cards
        strength = (
            postflop_strength(hole, board) if board else preflop_strength(hole)
        )

        can_raise = game_state.can_raise or game_state.can_bet
        if can_raise and strength >= 0.75:
            return Response.raise_to(self._size(game_state, strength))

        to_call = game_state.call_amount
        if to_call == 0:
            return Response.call()  # free: check

        # Pot odds: call when our strength beats the price we are given.
        price = to_call / (game_state.pot_size + to_call)
        if strength >= price + 0.1:
            return Response.call()
        return Response.fold()

    @staticmethod
    def _size(game_state: GameState, strength: float) -> int:
        """Bet about 2/3 pot, clamped to the legal range."""
        low = game_state.min_raise_to or 1
        high = game_state.max_raise_to or low
        target = game_state.my_bet + int(game_state.pot_size * 2 / 3)
        return max(min(target, high), min(low, high))
