from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Tuple

from .action_engine import ActionEngine
from .match_runtime import MatchRuntime
from .showdown_resolver import ShowdownResolver
from .state_projection import StateProjection


LogEventCallback = Callable[[MatchRuntime, str, Dict[str, Any]], None]


class RuntimeFlowCoordinator:
    """Coordinates turn progression and showdown settlement for a runtime."""

    def __init__(
        self,
        *,
        action_engine: ActionEngine,
        state_projection: StateProjection,
        showdown: ShowdownResolver,
        log_event: LogEventCallback,
    ) -> None:
        self._action_engine = action_engine
        self._state_projection = state_projection
        self._showdown = showdown
        self._log_event = log_event

    def prepare_turn_event(
        self, runtime: MatchRuntime
    ) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
        if runtime.status != "running":
            return None, None

        actor_index = self.current_actor_index(runtime)
        if actor_index is None:
            return None, None

        seat = runtime.players[actor_index]
        runtime.turn_id += 1

        state = self._state_projection.build_public_state(
            runtime,
            seat.player_id,
            actor_index,
        )
        legal_actions = self._action_engine.legal_actions(runtime, actor_index)

        event = {
            "type": "your_turn",
            "match_id": runtime.match_id,
            "turn_id": runtime.turn_id,
            "state": {
                **state,
                "hole_cards": state["players"][actor_index].get("hole_cards", []),
                "legal_actions": legal_actions,
                "min_raise_to": self._action_engine.min_raise_to(runtime, actor_index),
                "max_raise_to": seat.curr_bet_amount + seat.curr_balance,
            },
        }
        self._log_event(
            runtime,
            "turn_started",
            {"player_id": seat.player_id, "turn_id": runtime.turn_id},
        )
        return seat.player_id, event

    def advance_and_settle_if_ready(
        self, runtime: MatchRuntime
    ) -> Optional[Dict[str, Any]]:
        if self._action_engine.remaining_players(runtime) == 1:
            showdown = self._showdown.settle_fold_win(runtime)
            self._log_event(runtime, "showdown", {"results": showdown["results"]})
            return showdown

        while not runtime.engine.round_has_pending_actions():
            if runtime.engine.curr_street == "showdown":
                showdown = self._showdown.settle_showdown(runtime)
                self._log_event(runtime, "showdown", {"results": showdown["results"]})
                return showdown

            runtime.engine.advance_street()
            self._log_event(
                runtime,
                "street_advanced",
                {
                    "street": runtime.engine.curr_street,
                    "board": self._state_projection.build_public_state(
                        runtime,
                        None,
                        self.current_actor_index(runtime),
                    )["board"],
                },
            )

            if runtime.engine.curr_street == "showdown":
                showdown = self._showdown.settle_showdown(runtime)
                self._log_event(runtime, "showdown", {"results": showdown["results"]})
                return showdown

            next_index = self._action_engine.next_eligible_player(runtime, 0)
            if next_index is None:
                showdown = self._showdown.settle_showdown(runtime)
                self._log_event(runtime, "showdown", {"results": showdown["results"]})
                return showdown

            runtime.engine.turn_index = next_index
            if not self._action_engine.all_remaining_all_in(runtime):
                break

        return None

    def current_actor_index(self, runtime: MatchRuntime) -> Optional[int]:
        if not runtime.players:
            return None

        current = runtime.engine.turn_index % len(runtime.players)
        seat = runtime.players[current]
        if not seat.is_folded and not seat.is_all_in:
            return current

        next_index = self._action_engine.next_eligible_player(runtime, current + 1)
        if next_index is None:
            return None
        runtime.engine.turn_index = next_index
        return next_index

    def build_blind_events(self, runtime: MatchRuntime) -> List[Dict[str, Any]]:
        if len(runtime.engine.preflop_moves) < 2:
            return []

        small_blind = runtime.engine.preflop_moves[0]
        big_blind = runtime.engine.preflop_moves[1]
        return [
            {
                "type": "action",
                "match_id": runtime.match_id,
                "player_id": small_blind[0],
                "action": "post_small_blind",
                "amount": small_blind[2],
            },
            {
                "type": "action",
                "match_id": runtime.match_id,
                "player_id": big_blind[0],
                "action": "post_big_blind",
                "amount": big_blind[2],
            },
        ]
