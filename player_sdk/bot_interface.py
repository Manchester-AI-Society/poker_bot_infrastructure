from __future__ import annotations

from abc import ABC, abstractmethod

from .models import GameState, Response


class PokerBot(ABC):
    """Interface competitors implement to provide bot actions."""

    @abstractmethod
    def act(self, game_state: GameState) -> Response:
        """Returns this turn's move as a ``Response``.

        ``Response.fold()``, ``Response.call()``, ``Response.raise_to(n)`` or
        ``Response.all_in()``. Anything else is a fault.
        """
        raise NotImplementedError
