"""Tests for GameStateParser payload tolerance."""

from __future__ import annotations

import pytest

from player_sdk.parser import GameStateParser


def base_players():
    return [
        {"id": "p1", "stack": 980, "bet": 20, "folded": False},
        {"id": "p2", "stack": 1000, "bet": 10, "folded": False},
    ]


class TestParse:
    def test_http_merged_shape(self):
        state = GameStateParser().parse(
            {
                "match_id": "m1",
                "state": {
                    "players": base_players(),
                    "pot": 30,
                    "board": ["2s", "3s", "4s"],
                    "street": "flop",
                    "status": "running",
                    "current_player_id": "p1",
                    "turn_id": 4,
                    "legal_actions": ["fold", "call", "raise_to"],
                    "min_raise_to": 40,
                },
                "action_history": [
                    {"player_id": "p2", "action": "bet", "amount": 10}
                ],
            },
            hero_index=0,
        )
        assert state.player_ids == ("p1", "p2")
        assert state.stack_sizes == (980, 1000)
        assert state.current_bets == (20, 10)
        assert state.community_cards == ("2s", "3s", "4s")
        assert state.pot_size == 30
        assert state.current_player_index == 0
        assert state.turn_id == 4
        assert state.status == "running"
        assert state.my_index == 0
        assert state.call_amount == 0 or state.call_amount == 10
        assert state.action_history[0].action == "bet"

    def test_websocket_your_turn_shape(self):
        state = GameStateParser().parse(
            {
                "type": "your_turn",
                "match_id": "m1",
                "turn_id": 7,
                "state": {
                    "players": base_players(),
                    "pot": 130,
                    "board": [],
                    "street": "preflop",
                    "status": "running",
                    "current_player_id": "p1",
                    "turn_id": 7,
                    "hole_cards": ["As", "Kd"],
                    "legal_actions": ["fold", "call", "raise_to"],
                    "min_raise_to": 40,
                    "max_raise_to": 1000,
                },
            },
            hero_index=0,
        )
        assert state.hole_cards == ("As", "Kd")
        assert state.turn_id == 7
        assert state.min_raise_to == 40
        assert state.max_raise_to == 1000
        assert state.legal_actions == ("fold", "call", "raise_to")

    def test_key_spelling_tolerance(self):
        state = GameStateParser().parse(
            {
                "players": [
                    {"id": "p1", "stack_size": 500, "current_bet": 15},
                    {"id": "p2", "stack_size": 500, "committed": 30},
                ],
                "community_cards": ["2s"],
                "pot_size": 45,
                "current_player_index": 0,
                "minimum_raise": 25,
            }
        )
        assert state.stack_sizes == (500, 500)
        assert state.current_bets == (15, 30)
        assert state.minimum_raise == 25

    def test_call_amount_derived_from_bets(self):
        state = GameStateParser().parse(
            {
                "players": [
                    {"id": "p1", "stack": 500, "bet": 10},
                    {"id": "p2", "stack": 500, "bet": 40},
                ],
                "pot": 50,
                "current_player_index": 0,
            },
            hero_index=0,
        )
        assert state.call_amount == 30

    def test_missing_players_raises(self):
        with pytest.raises(ValueError):
            GameStateParser().parse({"pot": 0})

    def test_missing_current_actor_raises(self):
        with pytest.raises(ValueError):
            GameStateParser().parse({"players": base_players()})

    def test_parse_json_round_trip(self):
        import json

        payload = {
            "players": base_players(),
            "current_player_id": "p2",
            "pot": 30,
        }
        state = GameStateParser().parse_json(json.dumps(payload))
        assert state.current_player_index == 1
