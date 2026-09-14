"""Tests for client action translation and submission guards."""

from __future__ import annotations

import pytest

from player_sdk.bot_interface import PokerBot
from player_sdk.client import PokerEngineClient, translate_action
from player_sdk.models import Action, GameState


class StubBot(PokerBot):
    def act(self, game_state: GameState) -> Action:
        return Action.call()


def make_state(**overrides) -> GameState:
    defaults = dict(
        hole_cards=("As", "Kd"),
        community_cards=(),
        pot_size=30,
        stack_sizes=(1000, 1000),
        current_bets=(20, 10),
        current_player_index=0,
        call_amount=10,
        minimum_raise=20,
        action_history=(),
        turn_id=3,
        legal_actions=("fold", "call", "raise_to"),
        my_index=0,
        street="preflop",
        status="running",
        player_ids=("p1", "p2"),
    )
    defaults.update(overrides)
    return GameState(**defaults)


def make_client(**overrides) -> PokerEngineClient:
    params = dict(
        base_url="http://127.0.0.1:8000",
        match_id="m1",
        bot=StubBot(),
        player_id="p1",
        player_index=0,
        api_key="key",
    )
    params.update(overrides)
    return PokerEngineClient(**params)


class TestTranslateAction:
    def test_fold(self):
        assert translate_action(Action.fold(), make_state()) == (
            "fold",
            None,
        )

    def test_call_with_amount_owed(self):
        assert translate_action(Action.call(), make_state()) == (
            "call",
            None,
        )

    def test_call_with_no_amount_becomes_check(self):
        state = make_state(call_amount=0)
        assert translate_action(Action.call(), state) == ("check", None)

    def test_raise_with_call_owed_becomes_raise_to(self):
        assert translate_action(Action.raise_to(60), make_state()) == (
            "raise_to",
            60,
        )

    def test_raise_with_no_call_becomes_bet(self):
        state = make_state(call_amount=0)
        assert translate_action(Action.raise_to(60), state) == ("bet", 60)


class TestSendActionGuards:
    def test_turn_id_included_when_positive(self):
        client = make_client()
        captured = {}
        client._request = lambda method, path, payload=None, headers=None: (
            captured.update(method=method, path=path, payload=payload),
            {},
        )[1]
        client.send_action(Action.call(), game_state=make_state(turn_id=5))
        assert captured["payload"]["turn_id"] == 5
        assert captured["payload"]["action"] == "call"

    def test_turn_id_omitted_when_zero(self):
        client = make_client()
        captured = {}
        client._request = lambda method, path, payload=None, headers=None: (
            captured.update(payload=payload),
            {},
        )[1]
        client.send_action(Action.call(), game_state=make_state(turn_id=0))
        assert "turn_id" not in captured["payload"]

    def test_api_key_header_attached(self):
        client = make_client()
        captured = {}
        client._request = lambda method, path, payload=None, headers=None: (
            captured.update(headers=headers),
            {},
        )[1]
        client.send_action(Action.fold(), game_state=make_state())
        assert captured["headers"]["X-API-Key"] == "key"


class TestMaybeActGuards:
    def test_no_action_while_waiting(self):
        client = make_client()
        client.last_state = make_state(status="waiting", turn_id=0)
        assert client.maybe_act_on_current_state() is None

    def test_no_action_when_finished(self):
        client = make_client()
        client.last_state = make_state(status="finished")
        assert client.maybe_act_on_current_state() is None

    def test_no_action_on_other_players_turn(self):
        client = make_client()
        client.last_state = make_state(current_player_index=1)
        assert client.maybe_act_on_current_state() is None

    def test_acts_on_running_turn(self):
        client = make_client()
        client.last_state = make_state()
        client.send_action = lambda action, game_state=None: {"ok": True}
        assert client.maybe_act_on_current_state() == {"ok": True}

    def test_requires_state(self):
        client = make_client()

        with pytest.raises(RuntimeError):
            client.maybe_act_on_current_state()


class TestSeatDiscovery:
    def test_discovers_seat_from_players_list(self):
        client = make_client(player_id="p2", player_index=None)
        payload = {
            "state": {
                "players": [
                    {"id": "p1", "stack": 100, "bet": 0},
                    {"id": "p2", "stack": 200, "bet": 0},
                ],
                "current_player_id": "p1",
            }
        }
        client._request = lambda *a, **k: payload
        client.fetch_state_snapshot()
        assert client.player_index == 1
        assert client.last_state.my_index == 1


class TestMembershipValidation:
    def payload_for(self, status="running"):
        return {
            "state": {
                "players": [
                    {"id": "p1", "stack": 100, "bet": 0},
                    {"id": "p2", "stack": 200, "bet": 0},
                ],
                "current_player_id": "p1",
                "status": status,
            }
        }

    def test_foreign_player_raises(self):
        client = make_client(player_id="p3", player_index=None)
        client._request = lambda *a, **k: self.payload_for()
        with pytest.raises(RuntimeError, match="not a player in match"):
            client.fetch_state_snapshot()

    def test_member_does_not_raise(self):
        client = make_client(player_id="p1", player_index=None)
        client._request = lambda *a, **k: self.payload_for()
        client.fetch_state_snapshot()
        assert client.player_index == 0

    def test_finished_match_does_not_raise_for_foreign_player(self):
        client = make_client(player_id="p3", player_index=None)
        client._request = lambda *a, **k: self.payload_for("finished")
        state = client.fetch_state_snapshot()
        assert state.status == "finished"

    def test_missing_players_list_is_tolerated(self):
        client = make_client(player_id="p3", player_index=None)
        client._validate_membership({"pot": 0})
        client._validate_membership({"players": []})
