from __future__ import annotations

from typing import Any, Dict, Optional

from .models import InvalidActionError, MatchState


class GameStateMixin:
    def _state_for_player(
        self, match: MatchState, viewer_id: Optional[str]
    ) -> Dict[str, Any]:
        players_state = []
        for player in match.players:
            entry: Dict[str, Any] = {
                "id": player.player_id,
                "stack": player.stack,
                "bet": player.committed,
                "folded": player.folded,
                "all_in": player.all_in,
            }
            if viewer_id is not None and viewer_id == player.player_id:
                entry["hole_cards"] = list(player.hole_cards)
            players_state.append(entry)

        current_player_id = None
        if match.acting_index is not None:
            current_player_id = match.players[match.acting_index].player_id

        state = {
            "players": players_state,
            "pot": match.pot,
            "board": list(match.board),
            "street": match.street,
            "status": match.status,
            "current_player_id": current_player_id,
            "turn_id": match.turn_id,
        }

        if (
            viewer_id is not None
            and current_player_id == viewer_id
            and match.status == "running"
        ):
            viewer_index = self._player_index(match, viewer_id)
            state["legal_actions"] = self._legal_actions(match, viewer_index)

        return state

    def _player_index(self, match: MatchState, player_id: str) -> int:
        for index, player in enumerate(match.players):
            if player.player_id == player_id:
                return index
        raise InvalidActionError(f"Unknown player_id '{player_id}'")
