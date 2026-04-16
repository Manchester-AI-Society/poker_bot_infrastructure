"""Compatibility re-exports for legacy server.game imports."""

from game import (
    GameService,
    InvalidActionError,
    MatchNotFoundError,
    MatchState,
    MatchStateError,
    PlayerSeat,
)

__all__ = [
    "GameService",
    "InvalidActionError",
    "MatchNotFoundError",
    "MatchState",
    "MatchStateError",
    "PlayerSeat",
]
