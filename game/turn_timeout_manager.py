from __future__ import annotations

import asyncio
from logging import Logger
from typing import Awaitable, Callable, Optional

from .action_engine import ActionEngine
from .match_runtime import MatchRuntime

GetMatchCallback = Callable[[str], MatchRuntime]
SubmitActionCallback = Callable[..., Awaitable[None]]


class TurnTimeoutManager:
    """Schedules and resolves per-turn timeouts."""

    def __init__(
        self,
        *,
        action_engine: ActionEngine,
        get_match: GetMatchCallback,
        submit_action: SubmitActionCallback,
        logger: Logger,
    ) -> None:
        """Initialises timeout scheduling dependencies."""
        self._action_engine = action_engine
        self._get_match = get_match
        self._submit_action = submit_action
        self._logger = logger

    def schedule(
        self,
        runtime: MatchRuntime,
        player_id: str,
        turn_id: int,
    ) -> None:
        """Schedules a timeout task for the current turn."""
        self.cancel(runtime)
        runtime.turn_task = asyncio.create_task(
            self._timeout_task(
                runtime.match_id,
                player_id,
                turn_id,
                runtime.turn_timeout_seconds,
            )
        )

    def cancel(self, runtime: MatchRuntime) -> None:
        """Cancels any active timeout task for the runtime."""
        task = runtime.turn_task
        if task is not None and not task.done():
            task.cancel()
        runtime.turn_task = None

    async def _timeout_task(
        self,
        match_id: str,
        player_id: str,
        turn_id: int,
        timeout_seconds: int,
    ) -> None:
        """Executes fallback action submission when a turn times out."""
        try:
            await asyncio.sleep(timeout_seconds)
            runtime = self._get_match(match_id)
            actor_index = runtime.player_index(player_id)
            legal_actions = self._action_engine.legal_actions(runtime, actor_index)
            fallback_action = "check" if "check" in legal_actions else "fold"
            await self._submit_action(
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
            self._logger.exception(
                "Timeout task failed for match_id=%s player_id=%s turn_id=%s",
                match_id,
                player_id,
                turn_id,
            )
