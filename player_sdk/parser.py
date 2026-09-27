from __future__ import annotations

import json
from typing import Any, Mapping, Optional, Sequence, Tuple

from .models import ActionRecord, GameState


class GameStateParser:
    """Parses engine payloads into immutable GameState objects."""

    def parse_json(
        self, raw_json: str, hero_index: Optional[int] = None
    ) -> GameState:
        payload = json.loads(raw_json)
        if not isinstance(payload, Mapping):
            raise ValueError("Expected top-level JSON object")
        return self.parse(payload, hero_index=hero_index)

    def parse(
        self,
        payload: Mapping[str, Any],
        hero_index: Optional[int] = None,
    ) -> GameState:
        inner = payload.get("state")
        state_payload = inner if isinstance(inner, Mapping) else payload

        players = state_payload.get("players")
        if (
            not isinstance(players, Sequence)
            or isinstance(players, (str, bytes))
            or not players
        ):
            raise ValueError(
                "State payload must include a non-empty players list"
            )

        stack_sizes = []
        current_bets = []
        player_ids = []
        folded = []
        all_in = []
        resolved_hole_cards: Tuple[str, ...] = self._parse_cards(
            state_payload.get("hole_cards", ())
        )
        current_player_index = self._parse_current_player_index(
            state_payload, players
        )

        for index, player in enumerate(players):
            if not isinstance(player, Mapping):
                raise ValueError("Each player entry must be an object")
            stack_sizes.append(
                int(player.get("stack", player.get("stack_size", 0)))
            )
            current_bets.append(
                int(
                    player.get(
                        "bet",
                        player.get("current_bet", player.get("committed", 0)),
                    )
                )
            )
            player_ids.append(
                None if player.get("id") is None else str(player.get("id"))
            )
            folded.append(bool(player.get("folded", False)))
            all_in.append(bool(player.get("all_in", False)))
            if (
                not resolved_hole_cards
                and hero_index is not None
                and index == hero_index
            ):
                resolved_hole_cards = self._parse_cards(
                    player.get("hole_cards", ())
                )

        community_cards = self._parse_cards(
            state_payload.get(
                "community_cards", state_payload.get("board", ())
            )
        )
        pot_size = int(
            state_payload.get("pot_size", state_payload.get("pot", 0))
        )

        call_amount = self._parse_call_amount(
            state_payload, current_bets, hero_index
        )
        minimum_raise = int(
            state_payload.get(
                "minimum_raise",
                state_payload.get(
                    "min_raise", state_payload.get("min_raise_to", 0)
                ),
            )
        )

        action_history = self._parse_action_history(
            state_payload.get(
                "action_history", payload.get("action_history", ())
            )
        )

        turn_id = state_payload.get("turn_id", payload.get("turn_id"))
        legal_actions = state_payload.get(
            "legal_actions", payload.get("legal_actions", ())
        )
        street = state_payload.get("street", payload.get("street"))
        status = state_payload.get("status", payload.get("status"))
        min_raise_to = state_payload.get(
            "min_raise_to", payload.get("min_raise_to")
        )
        max_raise_to = state_payload.get(
            "max_raise_to", payload.get("max_raise_to")
        )

        return GameState(
            hole_cards=resolved_hole_cards,
            community_cards=community_cards,
            pot_size=pot_size,
            stack_sizes=tuple(stack_sizes),
            current_bets=tuple(current_bets),
            current_player_index=current_player_index,
            call_amount=call_amount,
            minimum_raise=minimum_raise,
            action_history=action_history,
            turn_id=(None if turn_id is None else int(turn_id)),
            legal_actions=self._parse_str_tuple(legal_actions),
            my_index=hero_index,
            street=None if street is None else str(street),
            status=None if status is None else str(status),
            player_ids=tuple(player_ids),
            folded=tuple(folded),
            all_in=tuple(all_in),
            min_raise_to=(None if min_raise_to is None else int(min_raise_to)),
            max_raise_to=(None if max_raise_to is None else int(max_raise_to)),
        )

    def _parse_current_player_index(
        self, state_payload: Mapping[str, Any], players: Sequence[Any]
    ) -> int:
        if "current_player_index" in state_payload:
            return int(state_payload["current_player_index"])

        current_player_id = state_payload.get("current_player_id")
        if current_player_id is not None:
            player_id = str(current_player_id)
            for index, player in enumerate(players):
                if (
                    isinstance(player, Mapping)
                    and str(player.get("id")) == player_id
                ):
                    return index
            raise ValueError("current_player_id was not found in players")

        raise ValueError(
            "State payload must include current_player_index"
            " or current_player_id"
        )

    def _parse_call_amount(
        self,
        state_payload: Mapping[str, Any],
        current_bets: Sequence[int],
        hero_index: Optional[int],
    ) -> int:
        if "call_amount" in state_payload:
            return int(state_payload["call_amount"])

        if (
            hero_index is None
            or hero_index < 0
            or hero_index >= len(current_bets)
        ):
            return 0

        return max(0, max(current_bets) - current_bets[hero_index])

    def _parse_action_history(
        self, raw_history: Any
    ) -> Tuple[ActionRecord, ...]:
        if raw_history is None:
            return ()
        if not isinstance(raw_history, Sequence) or isinstance(
            raw_history, (str, bytes)
        ):
            raise ValueError("action_history must be a sequence")

        rows = []
        for item in raw_history:
            if not isinstance(item, Mapping):
                continue
            rows.append(
                ActionRecord(
                    player_id=(
                        None
                        if item.get("player_id") is None
                        else str(item.get("player_id"))
                    ),
                    action=str(item.get("action", "")),
                    amount=(
                        None
                        if item.get("amount") is None
                        else int(item.get("amount"))
                    ),
                    street=(
                        None
                        if item.get("street") is None
                        else str(item.get("street"))
                    ),
                    timestamp=(
                        None
                        if item.get("timestamp") is None
                        else float(item.get("timestamp"))
                    ),
                )
            )
        return tuple(rows)

    def _parse_cards(self, raw_cards: Any) -> Tuple[str, ...]:
        if raw_cards is None:
            return ()
        if not isinstance(raw_cards, Sequence) or isinstance(
            raw_cards, (str, bytes)
        ):
            raise ValueError("cards must be a sequence")
        return tuple(str(card) for card in raw_cards)

    def _parse_str_tuple(self, values: Any) -> Tuple[str, ...]:
        if values is None:
            return ()
        if not isinstance(values, Sequence) or isinstance(
            values, (str, bytes)
        ):
            raise ValueError("legal_actions must be a sequence")
        return tuple(str(value) for value in values)
