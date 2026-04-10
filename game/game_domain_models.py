from __future__ import annotations

import asyncio
import time
from collections import deque
from dataclasses import dataclass, field
from typing import (
    Any,
    Awaitable,
    Callable,
    Deque,
    Dict,
    Iterable,
    List,
    Optional,
)


class MatchNotFoundError(KeyError):
    pass


class MatchStateError(RuntimeError):
    pass


class InvalidActionError(ValueError):
    pass


BroadcastCallback = Callable[[Iterable[str], Dict[str, Any]], Awaitable[None]]
DirectCallback = Callable[[str, Dict[str, Any]], Awaitable[None]]


@dataclass
class PlayerSeat:
    player_id: str
    stack: int
    hole_cards: List[str] = field(default_factory=list)
    committed: int = 0
    folded: bool = False
    all_in: bool = False
    acted: bool = False


@dataclass
class MatchState:
    match_id: str
    players: List[PlayerSeat]
    small_blind: int
    big_blind: int
    turn_timeout_seconds: int
    status: str = "waiting"
    street: str = "preflop"
    dealer_index: int = 0
    acting_index: Optional[int] = None
    current_bet: int = 0
    min_raise_size: int = 0
    pot: int = 0
    board: List[str] = field(default_factory=list)
    deck: List[str] = field(default_factory=list)
    turn_id: int = 0
    event_log_limit: int = 2000
    action_log: Deque[Dict[str, Any]] = field(default_factory=deque)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    turn_task: Optional[asyncio.Task] = None
    created_at: float = field(default_factory=time.time)
    paused_at: Optional[float] = None
    paused_by: Optional[str] = None
    pause_reason: Optional[str] = None
    resumed_at: Optional[float] = None
    admin_actions: List[Dict[str, Any]] = field(default_factory=list)
