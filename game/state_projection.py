from __future__ import annotations

from typing import Any, Dict, Optional

from .action_engine import ActionEngine
from .poker_card import cards_to_codes
from .match_runtime import MatchRuntime


class StateProjection:
    """Builds API state payloads from runtime state."""

    def __init__(self, action_engine: ActionEngine) -> None:
        """Initialises state projection with action rules access."""
        self._action_engine = action_engine

    def build_public_state(
        self,
        runtime: MatchRuntime,
        viewer_id: Optional[str],
        current_actor_index: Optional[int],
    ) -> Dict[str, Any]:
        """Builds a public state payload for a player viewer."""
        players_state = []
        for seat in runtime.players:
            entry: Dict[str, Any] = {
                "id": seat.player_id,
                "stack": seat.curr_balance,
                "bet": seat.curr_bet_amount,
                "folded": seat.is_folded,
                "all_in": seat.is_all_in,
            }
            if viewer_id is not None and viewer_id == seat.player_id:
                entry["hole_cards"] = cards_to_codes(seat.cards)
            players_state.append(entry)

        current_player_id = None
        if current_actor_index is not None:
            current_player_id = runtime.players[current_actor_index].player_id

        state: Dict[str, Any] = {
            "players": players_state,
            "pot": runtime.engine.pot,
            "board": cards_to_codes(runtime.engine.board.get_revealed_cards()),
            "street": runtime.engine.curr_street,
            "status": runtime.status,
            "current_player_id": current_player_id,
            "turn_id": runtime.turn_id,
        }

        if (
            viewer_id is not None
            and current_player_id == viewer_id
            and runtime.status == "running"
            and current_actor_index is not None
        ):
            state["legal_actions"] = self._action_engine.legal_actions(
                runtime, current_actor_index
            )

        return state

    def build_admin_state(
        self,
        runtime: MatchRuntime,
        current_actor_index: Optional[int],
    ) -> Dict[str, Any]:
        """Builds a full administrative state payload for a match."""
        players = [
            {
                "id": seat.player_id,
                "stack": seat.curr_balance,
                "bet": seat.curr_bet_amount,
                "folded": seat.is_folded,
                "all_in": seat.is_all_in,
                "hole_cards": cards_to_codes(seat.cards),
            }
            for seat in runtime.players
        ]

        return {
            "match_id": runtime.match_id,
            "players": players,
            "pot": runtime.engine.pot,
            "board": cards_to_codes(runtime.engine.board.get_revealed_cards()),
            "street": runtime.engine.curr_street,
            "status": runtime.status,
            "dealer_index": 0,
            "acting_index": current_actor_index,
            "turn_id": runtime.turn_id,
            "event_log_limit": runtime.event_log_limit,
            "paused_at": runtime.paused_at,
            "paused_by": runtime.paused_by,
            "pause_reason": runtime.pause_reason,
            "resumed_at": runtime.resumed_at,
        }
