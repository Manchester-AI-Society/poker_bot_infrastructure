from __future__ import annotations

import logging
import time
import uuid
from typing import Any, Dict, List, Optional

from server.api_request_models import CreateMatchRequest

from .action_engine import ActionEngine
from .match_runtime import MatchRuntime
from .runtime_flow import RuntimeFlowCoordinator
from .showdown_resolver import ShowdownResolver
from .state_projection import StateProjection
from .turn_timeout_manager import TurnTimeoutManager
from .game_domain_models import (
    BroadcastCallback,
    DirectCallback,
    InvalidActionError,
    MatchNotFoundError,
    MatchStateError,
)
from .player import player
from .poker_game import pokerGame

LOGGER = logging.getLogger(__name__)


class GameService:
    """core game service with async server integration."""

    def __init__(self) -> None:
        self._matches: Dict[str, MatchRuntime] = {}
        self._broadcast_cb: Optional[BroadcastCallback] = None
        self._direct_cb: Optional[DirectCallback] = None
        self._action_engine = ActionEngine()
        self._state_projection = StateProjection(self._action_engine)
        self._showdown = ShowdownResolver()
        self._runtime_flow = RuntimeFlowCoordinator(
            action_engine=self._action_engine,
            state_projection=self._state_projection,
            showdown=self._showdown,
            log_event=self._log_event,
        )
        self._timeout_manager = TurnTimeoutManager(
            action_engine=self._action_engine,
            get_match=self.get_match,
            submit_action=self.submit_action,
            logger=LOGGER,
        )

    def set_event_handlers(
        self,
        *,
        broadcast_cb: BroadcastCallback,
        direct_cb: DirectCallback,
    ) -> None:
        self._broadcast_cb = broadcast_cb
        self._direct_cb = direct_cb

    def create_match(self, request: CreateMatchRequest) -> MatchRuntime:
        if len(request.player_ids) < 2:
            raise MatchStateError("At least 2 players are required")
        if len(set(request.player_ids)) != len(request.player_ids):
            raise MatchStateError("Duplicate player ids are not allowed")
        if request.small_blind >= request.big_blind:
            raise MatchStateError("big_blind must be larger than small_blind")

        seats = [
            player(curr_balance=request.starting_stack, player_id=player_id)
            for player_id in request.player_ids
        ]

        engine = pokerGame(
            players=seats,
            big_blind_amount=request.big_blind,
            small_blind_amount=request.small_blind,
        )

        match_id = uuid.uuid4().hex[:12]
        runtime = MatchRuntime(
            match_id=match_id,
            engine=engine,
            turn_timeout_seconds=request.turn_timeout_seconds,
            event_log_limit=request.event_log_limit,
        )

        self._matches[match_id] = runtime
        self._log_event(runtime, "match_created", {"player_ids": request.player_ids})
        return runtime

    def list_matches(self) -> List[Dict[str, Any]]:
        return [
            {
                "match_id": runtime.match_id,
                "status": runtime.status,
                "player_ids": [seat.player_id for seat in runtime.players],
                "created_at": runtime.created_at,
            }
            for runtime in self._matches.values()
        ]

    def get_match(self, match_id: str) -> MatchRuntime:
        runtime = self._matches.get(match_id)
        if runtime is None:
            raise MatchNotFoundError(match_id)
        return runtime

    def get_public_state(
        self, match_id: str, viewer_id: Optional[str] = None
    ) -> Dict[str, Any]:
        runtime = self.get_match(match_id)
        actor_index = self._runtime_flow.current_actor_index(runtime)
        return self._state_projection.build_public_state(
            runtime,
            viewer_id,
            actor_index,
        )

    def get_logs(self, match_id: str) -> List[Dict[str, Any]]:
        runtime = self.get_match(match_id)
        return list(runtime.action_log)

    def get_logs_page(
        self, match_id: str, *, offset: int = 0, limit: int = 100
    ) -> Dict[str, Any]:
        runtime = self.get_match(match_id)

        safe_offset = max(0, offset)
        safe_limit = min(max(1, limit), 1000)
        events = list(runtime.action_log)
        total = len(events)
        page = events[safe_offset : safe_offset + safe_limit]

        return {
            "events": page,
            "offset": safe_offset,
            "limit": safe_limit,
            "total": total,
            "has_more": safe_offset + safe_limit < total,
            "log_capacity": runtime.event_log_limit,
        }

    def get_full_state_for_admin(self, match_id: str) -> Dict[str, Any]:
        runtime = self.get_match(match_id)
        actor_index = self._runtime_flow.current_actor_index(runtime)
        return self._state_projection.build_admin_state(runtime, actor_index)

    def get_admin_actions(self, match_id: str) -> List[Dict[str, Any]]:
        runtime = self.get_match(match_id)
        return list(runtime.admin_actions)

    async def start_match(self, match_id: str) -> None:
        runtime = self.get_match(match_id)

        turn_player_id: Optional[str] = None
        turn_event: Optional[Dict[str, Any]] = None
        blind_events: List[Dict[str, Any]] = []

        async with runtime.lock:
            if runtime.status != "waiting":
                raise MatchStateError("Match has already started")

            runtime.engine.start_hand()
            runtime.status = "running"
            runtime.updated_at = time.time()
            blind_events = self._runtime_flow.build_blind_events(runtime)
            self._log_event(runtime, "hand_started", {})

            turn_player_id, turn_event = self._runtime_flow.prepare_turn_event(runtime)

        for event in blind_events:
            await self._broadcast_match_event(runtime, event)

        if turn_player_id and turn_event:
            await self._send_turn_event(turn_player_id, turn_event)
            self._timeout_manager.schedule(runtime, turn_player_id, turn_event["turn_id"])

    async def submit_action(
        self,
        *,
        match_id: str,
        player_id: str,
        action: str,
        amount: Optional[int],
        turn_id: Optional[int],
        from_timeout: bool = False,
    ) -> None:
        runtime = self.get_match(match_id)

        timeout_event: Optional[Dict[str, Any]] = None
        action_event: Optional[Dict[str, Any]] = None
        showdown_event: Optional[Dict[str, Any]] = None
        turn_player_id: Optional[str] = None
        turn_event: Optional[Dict[str, Any]] = None

        async with runtime.lock:
            if runtime.status != "running":
                raise MatchStateError("Match is not running")

            actor_index = runtime.player_index(player_id)
            current_index = self._runtime_flow.current_actor_index(runtime)
            if current_index is None or current_index != actor_index:
                raise InvalidActionError("It is not your turn")

            if turn_id is not None and turn_id != runtime.turn_id:
                raise InvalidActionError(
                    f"Stale turn id: got {turn_id}, expected {runtime.turn_id}"
                )

            if from_timeout:
                runtime.turn_task = None
                timeout_event = {
                    "type": "timeout",
                    "match_id": runtime.match_id,
                    "player_id": player_id,
                }
                self._log_event(runtime, "timeout", {"player_id": player_id})
            else:
                self._timeout_manager.cancel(runtime)

            normalized_action = "raise_to" if action == "raise" else action
            action_name, emitted_amount = self._action_engine.apply_action(
                runtime,
                actor_index,
                normalized_action,
                amount,
            )

            action_event = {
                "type": "action",
                "match_id": runtime.match_id,
                "player_id": player_id,
                "action": action_name,
            }
            if emitted_amount is not None:
                action_event["amount"] = emitted_amount

            self._log_event(
                runtime,
                "action",
                {
                    "player_id": player_id,
                    "action": action_name,
                    "amount": emitted_amount,
                    "street": runtime.engine.curr_street,
                    "pot": runtime.engine.pot,
                },
            )

            showdown_event = self._runtime_flow.advance_and_settle_if_ready(runtime)
            if showdown_event is None and runtime.status == "running":
                next_index = self._action_engine.next_eligible_player(
                    runtime,
                    actor_index + 1,
                )
                if next_index is not None:
                    runtime.engine.turn_index = next_index
                turn_player_id, turn_event = self._runtime_flow.prepare_turn_event(runtime)

        if timeout_event:
            await self._broadcast_match_event(runtime, timeout_event)
        if action_event:
            await self._broadcast_match_event(runtime, action_event)
        if showdown_event:
            self._timeout_manager.cancel(runtime)
            await self._broadcast_match_event(runtime, showdown_event)
        elif turn_player_id and turn_event:
            await self._send_turn_event(turn_player_id, turn_event)
            self._timeout_manager.schedule(runtime, turn_player_id, turn_event["turn_id"])

    async def pause_match(
        self, match_id: str, admin_id: str, reason: Optional[str]
    ) -> Dict[str, Any]:
        runtime = self.get_match(match_id)

        async with runtime.lock:
            if runtime.status != "running":
                raise MatchStateError("Only running matches can be paused")

            self._timeout_manager.cancel(runtime)
            runtime.status = "paused"
            runtime.paused_at = time.time()
            runtime.paused_by = admin_id
            runtime.pause_reason = reason
            runtime.updated_at = runtime.paused_at
            runtime.admin_actions.append(
                {
                    "timestamp": runtime.paused_at,
                    "admin_id": admin_id,
                    "action": "pause",
                    "reason": reason,
                }
            )
            self._log_event(
                runtime,
                "admin_pause",
                {"admin_id": admin_id, "reason": reason},
            )

        event = {
            "type": "match_paused",
            "match_id": match_id,
            "admin_id": admin_id,
            "reason": reason,
        }
        await self._broadcast_match_event(runtime, event)
        return event

    async def resume_match(
        self, match_id: str, admin_id: str, reason: Optional[str]
    ) -> Dict[str, Any]:
        runtime = self.get_match(match_id)
        turn_player_id: Optional[str] = None
        turn_event: Optional[Dict[str, Any]] = None

        async with runtime.lock:
            if runtime.status != "paused":
                raise MatchStateError("Only paused matches can be resumed")

            runtime.status = "running"
            runtime.resumed_at = time.time()
            runtime.updated_at = runtime.resumed_at
            runtime.admin_actions.append(
                {
                    "timestamp": runtime.resumed_at,
                    "admin_id": admin_id,
                    "action": "resume",
                    "reason": reason,
                }
            )
            self._log_event(
                runtime,
                "admin_resume",
                {"admin_id": admin_id, "reason": reason},
            )

            turn_player_id, turn_event = self._runtime_flow.prepare_turn_event(runtime)

        event = {
            "type": "match_resumed",
            "match_id": match_id,
            "admin_id": admin_id,
            "reason": reason,
        }
        await self._broadcast_match_event(runtime, event)

        if turn_player_id and turn_event:
            await self._send_turn_event(turn_player_id, turn_event)
            self._timeout_manager.schedule(runtime, turn_player_id, turn_event["turn_id"])

        return event

    async def end_match(
        self,
        match_id: str,
        admin_id: str,
        reason: Optional[str],
        mode: str,
    ) -> Dict[str, Any]:
        runtime = self.get_match(match_id)

        async with runtime.lock:
            if runtime.status not in {"running", "paused", "waiting"}:
                raise MatchStateError("Only active matches can be ended")

            self._timeout_manager.cancel(runtime)
            if mode == "refund_committed":
                for seat in runtime.players:
                    if seat.curr_bet_amount > 0:
                        seat.curr_balance += seat.curr_bet_amount
                        runtime.engine.pot -= seat.curr_bet_amount
                        seat.curr_bet_amount = 0
                runtime.engine.pot = max(0, runtime.engine.pot)

            runtime.status = "finished"
            runtime.engine.curr_street = "admin_ended"
            runtime.end_reason = reason
            now = time.time()
            runtime.updated_at = now
            runtime.admin_actions.append(
                {
                    "timestamp": now,
                    "admin_id": admin_id,
                    "action": "end",
                    "reason": reason,
                    "mode": mode,
                }
            )
            self._log_event(
                runtime,
                "admin_end",
                {"admin_id": admin_id, "reason": reason, "mode": mode},
            )

        results = [
            {
                "player_id": seat.player_id,
                "stack": seat.curr_balance,
                "committed": seat.curr_bet_amount,
            }
            for seat in runtime.players
        ]

        event = {
            "type": "match_ended",
            "match_id": match_id,
            "admin_id": admin_id,
            "reason": reason,
            "mode": mode,
            "results": results,
        }
        await self._broadcast_match_event(runtime, event)
        return event

    async def _broadcast_match_event(
        self, runtime: MatchRuntime, event: Dict[str, Any]
    ) -> None:
        if self._broadcast_cb is None:
            return
        await self._broadcast_cb(
            [seat.player_id for seat in runtime.players],
            event,
        )

    async def _send_turn_event(self, player_id: str, event: Dict[str, Any]) -> None:
        if self._direct_cb is None:
            return
        await self._direct_cb(player_id, event)

    def _log_event(
        self,
        runtime: MatchRuntime,
        event_type: str,
        payload: Dict[str, Any],
    ) -> None:
        runtime.action_log.append(
            {
                "timestamp": time.time(),
                "type": event_type,
                **payload,
            }
        )