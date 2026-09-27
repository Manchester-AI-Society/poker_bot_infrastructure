from __future__ import annotations

from abc import ABC, abstractmethod

from .models import Action, GameState


class PokerBot(ABC):
    """Interface competitors implement to provide bot actions."""

    @abstractmethod
    def act(self, game_state: GameState) -> Action:
        """Returns fold/call/raise(amount) for the current turn."""
        raise NotImplementedError
