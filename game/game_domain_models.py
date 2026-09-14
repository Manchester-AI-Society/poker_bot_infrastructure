from __future__ import annotations

from typing import Any, Awaitable, Callable, Dict, Iterable


class MatchNotFoundError(KeyError):
    pass


class MatchStateError(RuntimeError):
    pass


class InvalidActionError(ValueError):
    pass


BroadcastCallback = Callable[[Iterable[str], Dict[str, Any]], Awaitable[None]]
DirectCallback = Callable[[str, Dict[str, Any]], Awaitable[None]]
