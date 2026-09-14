from __future__ import annotations

import asyncio
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Deque, Dict, List, Optional

from .game_domain_models import InvalidActionError
from .player import Player
from .poker_game import PokerGame


@dataclass
class MatchRuntime:
    """In-memory runtime state for one interactive match."""

    match_id: str
    engine: PokerGame
    turn_timeout_seconds: int
    event_log_limit: int
    status: str = "waiting"
    turn_id: int = 0
    min_raise_size: int = 0
    created_at: float = field(default_factory=time.time)
    paused_at: Optional[float] = None
    paused_by: Optional[str] = None
    pause_reason: Optional[str] = None
    resumed_at: Optional[float] = None
    admin_actions: List[Dict[str, Any]] = field(default_factory=list)
    winner_ids: List[str] = field(default_factory=list)
    end_reason: Optional[str] = None
    updated_at: float = field(default_factory=time.time)
    turn_task: Optional[asyncio.Task[Any]] = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    action_log: Deque[Dict[str, Any]] = field(init=False)

    def __post_init__(self) -> None:
        """Initialises derived runtime values after dataclass construction."""
        self.action_log = deque(maxlen=self.event_log_limit)
        if self.min_raise_size <= 0:
            self.min_raise_size = int(self.engine.big_blind_amount)

    @property
    def players(self) -> List[Player]:
        """Returns the current player objects from the engine."""
        return self.engine.players

    def player_index(self, player_id: str) -> int:
        """Returns the seat index for a given player id."""
        for index, seat in enumerate(self.players):
            if seat.player_id == player_id:
                return index
        raise InvalidActionError(f"Unknown player_id '{player_id}'")
