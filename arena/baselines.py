"""Built-in reference bots, used for smoke tests and as sparring partners.

Reference them on the command line as ``@fold``, ``@call``, ``@random``
or ``@shove``.
"""

from __future__ import annotations

import random
from typing import Callable, Dict, Optional

from player_sdk.bot_interface import PokerBot
from player_sdk.models import Action, GameState

from .agents import LocalAgent
from .contestant import Contestant


class FoldBot(PokerBot):
    """Folds every hand (what a disabled bot is replaced with)."""

    def act(self, game_state: GameState) -> Action:
        return Action.fold()


class CallBot(PokerBot):
    """Checks or calls everything: the classic calling station."""

    def act(self, game_state: GameState) -> Action:
        return Action.call()


class ShoveBot(PokerBot):
    """Goes all-in whenever it can, otherwise calls."""

    def act(self, game_state: GameState) -> Action:
        if game_state.max_raise_to and game_state.can_raise:
            return Action.raise_to(game_state.max_raise_to)
        if game_state.can_bet and game_state.max_raise_to:
            return Action.raise_to(game_state.max_raise_to)
        return Action.call()


class RandomBot(PokerBot):
    """Picks uniformly among its legal action types with random sizes."""

    def __init__(self, seed: Optional[int] = None):
        self._rng = random.Random(seed)

    def act(self, game_state: GameState) -> Action:
        rng = self._rng
        roll = rng.random()
        can_raise = game_state.can_raise or game_state.can_bet
        if can_raise and roll < 0.35:
            low = game_state.min_raise_to or 1
            high = game_state.max_raise_to or low
            if rng.random() < 0.2:
                return Action.raise_to(high)
            return Action.raise_to(rng.randint(min(low, high), high))
        if roll < 0.45 and game_state.can_fold and not game_state.can_check:
            return Action.fold()
        return Action.call()


BASELINES: Dict[str, Callable[[], PokerBot]] = {
    "fold": FoldBot,
    "call": CallBot,
    "random": RandomBot,
    "shove": ShoveBot,
}


def baseline_contestant(name: str, **kwargs) -> Contestant:
    """Builds a contestant for ``@name`` (without the leading ``@``)."""
    try:
        bot_class = BASELINES[name]
    except KeyError:
        raise ValueError(
            f"unknown baseline '@{name}'; choose from "
            + ", ".join(f"@{key}" for key in sorted(BASELINES))
        ) from None
    return Contestant(
        name=f"@{name}",
        factory=lambda: LocalAgent(bot_class),
        **kwargs,
    )
