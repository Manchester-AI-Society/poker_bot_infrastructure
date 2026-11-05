"""Push/fold: shove the best hands all-in, fold (or check) everything else.

A deliberately simple strategy with a real place in poker: with a short
stack, going all-in or folding is often right. At 100 big blinds it is not
optimal, which is the point of the example: it wins small pots by making
opponents fold, and loses big ones when someone calls with a better hand. It
never needs to think after the flop because the hand is almost always decided
before it.

Try it:

    python -m arena match bots/push_fold call --deals 200
    python -m arena match bots/push_fold bots/tight_aggressive --deals 300
"""

from __future__ import annotations

from typing import Sequence

from player_sdk.bot_interface import PokerBot
from player_sdk.models import Action, GameState

RANKS = "23456789TJQKA"
SHOVE_AT = 0.72  # roughly the top 15% of starting hands
CALL_SHOVE_AT = 0.80  # call an all-in only with a premium hand


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


class PushFoldBot(PokerBot):
    def act(self, gs: GameState) -> Action:
        can_raise = gs.can_raise or gs.can_bet
        strength = preflop_strength(gs.hole_cards)

        if gs.is_preflop:
            to_call = gs.call_amount
            # A call that costs our whole stack is a shove.
            facing_shove = to_call > 0 and to_call >= (gs.my_stack or 0)
            if facing_shove:
                return (
                    Action.call()
                    if strength >= CALL_SHOVE_AT
                    else Action.fold()
                )
            if can_raise and strength >= SHOVE_AT:
                return Action.raise_to(gs.max_raise_to or gs.min_raise_to or 1)
            if to_call == 0:
                return Action.call()  # check the big blind option
            # Facing an ordinary raise: only the very best hands continue.
            return (
                Action.call() if strength >= CALL_SHOVE_AT else Action.fold()
            )

        # After the flop: check when free, never call big bets without much.
        if gs.call_amount == 0:
            return Action.call()
        price = gs.call_amount / (gs.pot_size + gs.call_amount)
        return Action.call() if price <= 0.25 else Action.fold()
