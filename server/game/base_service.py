from __future__ import annotations

import time
import uuid
from collections import deque
from typing import Any, Dict, List, Optional

from server.schemas import CreateMatchRequest

from .models import (
    BroadcastCallback,
    DirectCallback,
    MatchNotFoundError,
    MatchState,
    MatchStateError,
    PlayerSeat,
)


class GameServiceBase:
    def __init__(self) -> None:
        self._matches: Dict[str, MatchState] = {}
        self._broadcast_cb: Optional[BroadcastCallback] = None
        self._direct_cb: Optional[DirectCallback] = None

    def set_event_handlers(
        self,
        *,
        broadcast_cb: BroadcastCallback,
        direct_cb: DirectCallback,
    ) -> None:
        self._broadcast_cb = broadcast_cb
        self._direct_cb = direct_cb

    def create_match(self, request: CreateMatchRequest) -> MatchState:
        if len(request.player_ids) < 2:
            raise MatchStateError("At least 2 players are required")
        if len(set(request.player_ids)) != len(request.player_ids):
            raise MatchStateError("Duplicate player ids are not allowed")
        if request.small_blind >= request.big_blind:
            raise MatchStateError("big_blind must be larger than small_blind")

        seats = [
            PlayerSeat(player_id=player_id, stack=request.starting_stack)
            for player_id in request.player_ids
        ]
        match_id = uuid.uuid4().hex[:12]

        match = MatchState(
            match_id=match_id,
            players=seats,
            small_blind=request.small_blind,
            big_blind=request.big_blind,
            turn_timeout_seconds=request.turn_timeout_seconds,
            min_raise_size=request.big_blind,
            event_log_limit=request.event_log_limit,
        )
        match.action_log = deque(maxlen=request.event_log_limit)
        self._matches[match_id] = match
        self._log_event(
            match, "match_created", {"player_ids": request.player_ids}
        )
        return match

    def list_matches(self) -> List[Dict[str, Any]]:
        return [
            {
                "match_id": match.match_id,
                "status": match.status,
                "player_ids": [player.player_id for player in match.players],
                "created_at": match.created_at,
            }
            for match in self._matches.values()
        ]

    def get_match(self, match_id: str) -> MatchState:
        match = self._matches.get(match_id)
        if match is None:
            raise MatchNotFoundError(match_id)
        return match

    def get_public_state(
        self, match_id: str, viewer_id: Optional[str] = None
    ) -> Dict[str, Any]:
        match = self.get_match(match_id)
        return self._state_for_player(match, viewer_id)

    def get_logs(self, match_id: str) -> List[Dict[str, Any]]:
        match = self.get_match(match_id)
        return list(match.action_log)

    def get_logs_page(
        self, match_id: str, *, offset: int = 0, limit: int = 100
    ) -> Dict[str, Any]:
        match = self.get_match(match_id)

        safe_offset = max(0, offset)
        safe_limit = min(max(1, limit), 1000)

        events = list(match.action_log)
        total = len(events)
        page = events[safe_offset : safe_offset + safe_limit]

        return {
            "events": page,
            "offset": safe_offset,
            "limit": safe_limit,
            "total": total,
            "has_more": safe_offset + safe_limit < total,
            "log_capacity": match.event_log_limit,
        }

    async def _broadcast_match_event(
        self, match: MatchState, event: Dict[str, Any]
    ) -> None:
        if self._broadcast_cb is None:
            return
        await self._broadcast_cb(
            [player.player_id for player in match.players], event
        )

    async def _send_turn_event(
        self, player_id: str, event: Dict[str, Any]
    ) -> None:
        if self._direct_cb is None:
            return
        await self._direct_cb(player_id, event)

    def _log_event(
        self, match: MatchState, event_type: str, payload: Dict[str, Any]
    ) -> None:
        match.action_log.append(
            {
                "timestamp": time.time(),
                "type": event_type,
                "payload": payload,
            }
        )
