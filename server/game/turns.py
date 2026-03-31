from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional, Tuple

from .models import InvalidActionError, MatchState, MatchStateError

LOGGER = logging.getLogger(__name__)


class GameTurnMixin:
    async def start_match(self, match_id: str) -> None:
        match = self.get_match(match_id)

        turn_player_id: Optional[str] = None
        turn_event: Optional[Dict[str, Any]] = None
        blind_events: List[Dict[str, Any]] = []

        async with match.lock:
            if match.status != "waiting":
                raise MatchStateError("Match has already started")

            blind_events = self._start_hand(match)
            turn_player_id, turn_event = self._prepare_turn_event(match)

        for event in blind_events:
            await self._broadcast_match_event(match, event)

        if turn_player_id and turn_event:
            await self._send_turn_event(turn_player_id, turn_event)
            self._schedule_turn_timeout(
                match, turn_player_id, turn_event["turn_id"]
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
        match = self.get_match(match_id)

        timeout_event: Optional[Dict[str, Any]] = None
        action_event: Optional[Dict[str, Any]] = None
        showdown_event: Optional[Dict[str, Any]] = None
        turn_player_id: Optional[str] = None
        turn_event: Optional[Dict[str, Any]] = None

        async with match.lock:
            if match.status != "running":
                raise MatchStateError("Match is not running")

            actor_index = self._player_index(match, player_id)
            if match.acting_index != actor_index:
                raise InvalidActionError("It is not your turn")

            if turn_id is not None and turn_id != match.turn_id:
                raise InvalidActionError(
                    f"Stale turn id: got {turn_id}, expected {match.turn_id}"
                )

            if from_timeout:
                match.turn_task = None
                timeout_event = {
                    "type": "timeout",
                    "match_id": match.match_id,
                    "player_id": player_id,
                }
                self._log_event(match, "timeout", {"player_id": player_id})
            else:
                self._cancel_turn_timeout(match)

            normalized_action = "raise_to" if action == "raise" else action
            action_name, emitted_amount = self._apply_action(
                match, actor_index, normalized_action, amount
            )

            action_event = {
                "type": "action",
                "match_id": match.match_id,
                "player_id": player_id,
                "action": action_name,
            }
            if emitted_amount is not None:
                action_event["amount"] = emitted_amount

            if self._remaining_players(match) == 1:
                showdown_event = self._settle_fold_win(match)
            else:
                if self._is_round_complete(match):
                    showdown_event = self._advance_street(match)
                    if showdown_event is None and self._all_remaining_all_in(
                        match
                    ):
                        showdown_event = self._runout_and_showdown(match)
                else:
                    match.acting_index = self._next_eligible_player(
                        match, actor_index
                    )
                    if match.acting_index is None:
                        showdown_event = self._runout_and_showdown(match)

                if showdown_event is None and match.status == "running":
                    turn_player_id, turn_event = self._prepare_turn_event(
                        match
                    )

        if timeout_event:
            await self._broadcast_match_event(match, timeout_event)
        if action_event:
            await self._broadcast_match_event(match, action_event)
        if showdown_event:
            self._cancel_turn_timeout(match)
            await self._broadcast_match_event(match, showdown_event)
        elif turn_player_id and turn_event:
            await self._send_turn_event(turn_player_id, turn_event)
            self._schedule_turn_timeout(
                match, turn_player_id, turn_event["turn_id"]
            )

    def _prepare_turn_event(
        self, match: MatchState
    ) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
        if match.status != "running":
            return None, None
        if match.acting_index is None:
            return None, None

        player = match.players[match.acting_index]
        if player.folded or player.all_in:
            return None, None

        match.turn_id += 1
        legal_actions = self._legal_actions(match, match.acting_index)

        event = {
            "type": "your_turn",
            "match_id": match.match_id,
            "turn_id": match.turn_id,
            "state": {
                **self._state_for_player(match, player.player_id),
                "hole_cards": list(player.hole_cards),
                "legal_actions": legal_actions,
                "min_raise_to": self._min_raise_to(match, match.acting_index),
                "max_raise_to": player.committed + player.stack,
            },
        }
        self._log_event(
            match,
            "turn_started",
            {"player_id": player.player_id, "turn_id": match.turn_id},
        )
        return player.player_id, event

    def _schedule_turn_timeout(
        self, match: MatchState, player_id: str, turn_id: int
    ) -> None:
        self._cancel_turn_timeout(match)
        match.turn_task = asyncio.create_task(
            self._timeout_task(
                match.match_id, player_id, turn_id, match.turn_timeout_seconds
            )
        )

    def _cancel_turn_timeout(self, match: MatchState) -> None:
        task = match.turn_task
        if task is not None and not task.done():
            task.cancel()
        match.turn_task = None

    async def _timeout_task(
        self, match_id: str, player_id: str, turn_id: int, timeout_seconds: int
    ) -> None:
        try:
            await asyncio.sleep(timeout_seconds)
            match = self.get_match(match_id)
            state = self._state_for_player(match, player_id)
            fallback_action = (
                "check"
                if "check" in state.get("legal_actions", [])
                else "fold"
            )
            await self.submit_action(
                match_id=match_id,
                player_id=player_id,
                action=fallback_action,
                amount=None,
                turn_id=turn_id,
                from_timeout=True,
            )
        except asyncio.CancelledError:
            return
        except Exception:
            LOGGER.exception(
                "Timeout task failed for match_id=%s player_id=%s turn_id=%s",
                match_id,
                player_id,
                turn_id,
            )
            return
