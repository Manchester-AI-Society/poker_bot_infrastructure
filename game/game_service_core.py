from __future__ import annotations

import logging
import time
import uuid
from typing import Any, Callable, Dict, List, Optional

from .action_engine import apply_action, next_eligible_player
from .game_domain_models import (
    BroadcastCallback,
    DirectCallback,
    InvalidActionError,
    MatchNotFoundError,
    MatchStateError,
)
from .match_runtime import MatchRuntime
from .player import Player
from .poker_game import PokerGame
from .runtime_flow import (
    advance_and_settle_if_ready,
    begin_next_hand,
    current_actor_index,
    prepare_turn_event,
    resolve_match_progression,
)
from .state_projection import build_admin_state, build_public_state
from .turn_timeout_manager import TurnTimeoutManager

LOGGER = logging.getLogger(__name__)

ConnectedCheckCallback = Callable[[str], bool]


class GameService:
    """core game service with async server integration."""

    def __init__(self) -> None:
        """Initialises the game service and timeout scheduling."""
        self._matches: Dict[str, MatchRuntime] = {}
        self._broadcast_cb: Optional[BroadcastCallback] = None
        self._direct_cb: Optional[DirectCallback] = None
        self._connected_check: Optional[ConnectedCheckCallback] = None
        self._timeout_manager = TurnTimeoutManager(
            get_match=self.get_match,
            submit_action=self.submit_action,
            logger=LOGGER,
        )

    def set_event_handlers(
        self,
        *,
        broadcast_cb: BroadcastCallback,
        direct_cb: DirectCallback,
        connected_check: Optional[ConnectedCheckCallback] = None,
    ) -> None:
        """Registers broadcast, direct event, and connection callbacks."""
        self._broadcast_cb = broadcast_cb
        self._direct_cb = direct_cb
        self._connected_check = connected_check

    def create_match(
        self,
        *,
        player_ids: List[str],
        starting_stack: int = 1000,
        small_blind: int = 10,
        big_blind: int = 20,
        turn_timeout_seconds: int = 15,
        event_log_limit: int = 2000,
        max_hands: Optional[int] = None,
        wait_for_players: bool = True,
    ) -> MatchRuntime:
        """Creates and stores a new match runtime."""
        if len(player_ids) < 2:
            raise MatchStateError("At least 2 players are required")
        if len(set(player_ids)) != len(player_ids):
            raise MatchStateError("Duplicate player ids are not allowed")
        if small_blind >= big_blind:
            raise MatchStateError("big_blind must be larger than small_blind")
        if max_hands is not None and max_hands < 1:
            raise MatchStateError("max_hands must be at least 1 when set")

        seats = [
            Player(curr_balance=starting_stack, player_id=player_id)
            for player_id in player_ids
        ]

        engine = PokerGame(
            players=seats,
            big_blind_amount=big_blind,
            small_blind_amount=small_blind,
        )

        match_id = uuid.uuid4().hex[:12]
        runtime = MatchRuntime(
            match_id=match_id,
            engine=engine,
            turn_timeout_seconds=turn_timeout_seconds,
            event_log_limit=event_log_limit,
            max_hands=max_hands,
            wait_for_players=wait_for_players,
        )

        self._matches[match_id] = runtime
        self._log_event(runtime, "match_created", {"player_ids": player_ids})
        return runtime

    def list_matches(self) -> List[Dict[str, Any]]:
        """Returns summary metadata for all active matches."""
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
        """Returns a match runtime by identifier."""
        runtime = self._matches.get(match_id)
        if runtime is None:
            raise MatchNotFoundError(match_id)
        return runtime

    def get_public_state(
        self, match_id: str, viewer_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Builds the public state payload for a match viewer."""
        runtime = self.get_match(match_id)
        actor_index = current_actor_index(runtime)
        return build_public_state(
            runtime,
            viewer_id,
            actor_index,
        )

    def get_logs(self, match_id: str) -> List[Dict[str, Any]]:
        """Returns the full in-memory event log for a match."""
        runtime = self.get_match(match_id)
        return list(runtime.action_log)

    def get_logs_page(
        self, match_id: str, *, offset: int = 0, limit: int = 100
    ) -> Dict[str, Any]:
        """Returns a paginated slice of the event log for a match."""
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
        """Builds the full administrative state payload for a match."""
        runtime = self.get_match(match_id)
        actor_index = current_actor_index(runtime)
        return build_admin_state(runtime, actor_index)

    def get_admin_actions(self, match_id: str) -> List[Dict[str, Any]]:
        """Returns the audit trail of admin actions for a match."""
        runtime = self.get_match(match_id)
        return list(runtime.admin_actions)

    def _all_players_connected(self, runtime: MatchRuntime) -> bool:
        """Checks whether every match member has a live connection.

        Without a connection layer wired in (unit tests, embedded use)
        readiness cannot be observed and every player counts as ready.
        """
        if self._connected_check is None:
            return True
        return all(
            self._connected_check(seat.player_id) for seat in runtime.players
        )

    def _start_first_hand_locked(
        self, runtime: MatchRuntime
    ) -> tuple[List[Dict[str, Any]], Optional[str], Optional[Dict[str, Any]]]:
        """Deals the first hand; must be called under the runtime lock."""
        runtime.status = "running"
        runtime.updated_at = time.time()
        (
            blind_events,
            turn_player_id,
            turn_event,
        ) = begin_next_hand(runtime, self._log_event)
        return blind_events, turn_player_id, turn_event

    async def _announce_hand_opening(
        self,
        runtime: MatchRuntime,
        blind_events: List[Dict[str, Any]],
        turn_player_id: Optional[str],
        turn_event: Optional[Dict[str, Any]],
    ) -> None:
        """Broadcasts match/hand opening events and arms the turn timer."""
        await self._broadcast_match_event(
            runtime,
            {"type": "match_started", "match_id": runtime.match_id},
        )
        for event in blind_events:
            await self._broadcast_match_event(runtime, event)
        if turn_player_id and turn_event:
            await self._send_turn_event(turn_player_id, turn_event)
            self._timeout_manager.schedule(
                runtime, turn_player_id, turn_event["turn_id"]
            )

    async def start_match(
        self, match_id: str, *, force: bool = False
    ) -> Dict[str, Any]:
        """Starts (or arms) a waiting match.

        With the readiness gate enabled and ``force`` unset, the match
        stays ``waiting`` until every member has connected; the deal
        then happens automatically via ``on_player_connected``.
        """
        runtime = self.get_match(match_id)

        async with runtime.lock:
            if runtime.status != "waiting":
                raise MatchStateError("Match has already started")

            runtime.start_requested = True

            if (
                runtime.wait_for_players
                and not force
                and not self._all_players_connected(runtime)
            ):
                self._log_event(runtime, "match_armed", {})
                runtime.updated_at = time.time()
                return {
                    "match_id": match_id,
                    "status": "waiting",
                    "armed": True,
                }

            blind_events, turn_player_id, turn_event = (
                self._start_first_hand_locked(runtime)
            )

        await self._announce_hand_opening(
            runtime, blind_events, turn_player_id, turn_event
        )
        return {"match_id": match_id, "status": "running", "armed": False}

    async def on_player_connected(self, player_id: str) -> None:
        """Auto-starts armed matches whose members are now all online."""
        for runtime in list(self._matches.values()):
            if runtime.status != "waiting" or not runtime.start_requested:
                continue
            if not runtime.wait_for_players:
                continue
            if all(seat.player_id != player_id for seat in runtime.players):
                continue

            async with runtime.lock:
                if (
                    runtime.status != "waiting"
                    or not runtime.start_requested
                    or not self._all_players_connected(runtime)
                ):
                    continue
                blind_events, turn_player_id, turn_event = (
                    self._start_first_hand_locked(runtime)
                )

            await self._announce_hand_opening(
                runtime, blind_events, turn_player_id, turn_event
            )

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
        """Validates and applies a player action for the current turn."""
        runtime = self.get_match(match_id)

        timeout_event: Optional[Dict[str, Any]] = None
        action_event: Optional[Dict[str, Any]] = None
        showdown_event: Optional[Dict[str, Any]] = None
        match_ended_event: Optional[Dict[str, Any]] = None
        hand_broadcast_events: List[Dict[str, Any]] = []
        turn_player_id: Optional[str] = None
        turn_event: Optional[Dict[str, Any]] = None

        async with runtime.lock:
            if runtime.status != "running":
                raise MatchStateError("Match is not running")

            actor_index = runtime.player_index(player_id)
            current_index = current_actor_index(runtime)
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

            normalised_action = "raise_to" if action == "raise" else action
            action_name, emitted_amount = apply_action(
                runtime,
                actor_index,
                normalised_action,
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

            showdown_event = advance_and_settle_if_ready(
                runtime, self._log_event
            )
            if showdown_event is not None:
                (
                    match_ended_event,
                    hand_broadcast_events,
                    turn_player_id,
                    turn_event,
                ) = resolve_match_progression(runtime, self._log_event)
            elif runtime.status == "running":
                next_index = next_eligible_player(
                    runtime,
                    actor_index + 1,
                )
                if next_index is not None:
                    runtime.engine.turn_index = next_index
                turn_player_id, turn_event = prepare_turn_event(
                    runtime, self._log_event
                )

        if timeout_event:
            await self._broadcast_match_event(runtime, timeout_event)
        if action_event:
            await self._broadcast_match_event(runtime, action_event)
        if showdown_event:
            self._timeout_manager.cancel(runtime)
            await self._broadcast_match_event(runtime, showdown_event)
            for event in hand_broadcast_events:
                await self._broadcast_match_event(runtime, event)
            if match_ended_event is not None:
                await self._broadcast_match_event(runtime, match_ended_event)
                return
        if turn_player_id and turn_event:
            await self._send_turn_event(turn_player_id, turn_event)
            self._timeout_manager.schedule(
                runtime, turn_player_id, turn_event["turn_id"]
            )

    async def pause_match(
        self, match_id: str, admin_id: str, reason: Optional[str]
    ) -> Dict[str, Any]:
        """Pauses a running match by administrative command."""
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
        """Resumes a paused match and schedules the next turn."""
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

            turn_player_id, turn_event = prepare_turn_event(
                runtime, self._log_event
            )

        event = {
            "type": "match_resumed",
            "match_id": match_id,
            "admin_id": admin_id,
            "reason": reason,
        }
        await self._broadcast_match_event(runtime, event)

        if turn_player_id and turn_event:
            await self._send_turn_event(turn_player_id, turn_event)
            self._timeout_manager.schedule(
                runtime, turn_player_id, turn_event["turn_id"]
            )

        return event

    async def end_match(
        self,
        match_id: str,
        admin_id: str,
        reason: Optional[str],
        mode: str,
    ) -> Dict[str, Any]:
        """Ends an active match and broadcasts final results."""
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
        """Broadcasts an event to all players in a match."""
        if self._broadcast_cb is None:
            return
        await self._broadcast_cb(
            [seat.player_id for seat in runtime.players],
            event,
        )

    async def _send_turn_event(
        self, player_id: str, event: Dict[str, Any]
    ) -> None:
        """Sends a direct turn event to a single player."""
        if self._direct_cb is None:
            return
        await self._direct_cb(player_id, event)

    def _log_event(
        self,
        runtime: MatchRuntime,
        event_type: str,
        payload: Dict[str, Any],
    ) -> None:
        """Appends a timestamped event entry to the match log."""
        runtime.action_log.append(
            {
                "timestamp": time.time(),
                "type": event_type,
                **payload,
            }
        )
