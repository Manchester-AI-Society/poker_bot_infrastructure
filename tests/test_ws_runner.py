"""Unit tests for the realtime websocket runner message handling."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

import pytest

import player_sdk._ws as ws_module
from player_sdk._http import PlayerSDKAuthError
from player_sdk._ws import RealtimeBotRunner
from player_sdk.bot_interface import PokerBot
from player_sdk.models import Action, ActionRecord, GameState

try:
    from websockets.frames import Close
except ImportError:  # pragma: no cover - older websockets layouts
    from websockets.exceptions import Close  # type: ignore[attr-defined]

try:
    from websockets.exceptions import ConnectionClosed
except ImportError:  # pragma: no cover
    from websockets.connection import ConnectionClosed  # type: ignore


class CallingBot(PokerBot):
    def act(self, game_state: GameState) -> Action:
        return Action.call()


def your_turn_message(turn_id: int = 3) -> Dict[str, Any]:
    return {
        "type": "your_turn",
        "match_id": "m1",
        "turn_id": turn_id,
        "state": {
            "players": [
                {"id": "p1", "stack": 980, "bet": 10},
                {"id": "p2", "stack": 1000, "bet": 20},
            ],
            "pot": 30,
            "board": [],
            "street": "preflop",
            "status": "running",
            "current_player_id": "p1",
            "turn_id": turn_id,
            "hole_cards": ["As", "Kd"],
            "legal_actions": ["fold", "call", "raise_to"],
            "min_raise_to": 40,
            "max_raise_to": 1000,
        },
    }


def finished_state() -> GameState:
    return GameState(
        hole_cards=(),
        community_cards=(),
        pot_size=0,
        stack_sizes=(1200, 800),
        current_bets=(0, 0),
        current_player_index=0,
        call_amount=0,
        minimum_raise=0,
        action_history=(ActionRecord(player_id="p2", action="fold"),),
        status="finished",
        player_ids=("p1", "p2"),
        my_index=0,
    )


def running_state() -> GameState:
    state = finished_state()
    object.__setattr__(state, "status", "running")
    object.__setattr__(state, "current_player_index", 1)
    return state


class FakeWebSocket:
    def __init__(self, incoming: List[Dict[str, Any]]):
        self._incoming = list(incoming)
        self.sent: List[Dict[str, Any]] = []

    def send(self, data: str) -> None:
        self.sent.append(json.loads(data))

    def recv(self, timeout: Optional[float] = None):
        if self._incoming:
            return json.dumps(self._incoming.pop(0))
        raise TimeoutError()


def make_runner() -> RealtimeBotRunner:
    runner = RealtimeBotRunner(
        base_url="http://127.0.0.1:8000",
        match_id="m1",
        bot=CallingBot(),
        player_id="p1",
        api_key="key",
        verbose=False,
    )
    runner.client.fetch_action_history = lambda *a, **k: []
    runner.client.fetch_state_snapshot = lambda *a, **k: finished_state()
    runner.client.fetch_latest_state = lambda *a, **k: finished_state()
    return runner


class TestHandleYourTurn:
    def test_sends_translated_action_with_turn_id(self):
        runner = make_runner()
        socket = FakeWebSocket([])
        exit_state = runner._handle_your_turn(
            socket, your_turn_message(turn_id=3)
        )
        assert exit_state is None
        assert socket.sent == [
            {
                "type": "action",
                "match_id": "m1",
                "action": "call",
                "turn_id": 3,
            }
        ]

    def test_zero_turn_id_is_omitted(self):
        runner = make_runner()
        socket = FakeWebSocket([])
        runner._handle_your_turn(socket, your_turn_message(turn_id=0))
        assert "turn_id" not in socket.sent[0]

    def test_discovers_seat_from_players(self):
        runner = make_runner()
        runner.client.player_index = None
        socket = FakeWebSocket([])
        runner._handle_your_turn(socket, your_turn_message())
        assert runner.client.player_index == 0
        assert runner.client.last_state.my_index == 0
        assert runner.client.last_state.hole_cards == ("As", "Kd")

    def test_finished_state_returns_final_state(self):
        runner = make_runner()
        socket = FakeWebSocket([])
        message = your_turn_message()
        message["state"]["status"] = "finished"
        assert runner._handle_your_turn(socket, message) is not None
        assert socket.sent == []

    def test_malformed_state_is_ignored(self):
        runner = make_runner()
        socket = FakeWebSocket([])
        assert runner._handle_your_turn(socket, {"type": "your_turn"}) is None
        assert socket.sent == []


class TestMessageLoop:
    def test_showdown_does_not_end_a_multi_hand_match(self):
        runner = make_runner()
        socket = FakeWebSocket(
            [
                {"type": "showdown", "match_id": "m1", "results": []},
                your_turn_message(turn_id=4),
                {"type": "match_ended", "match_id": "m1"},
            ]
        )
        state = runner._message_loop(socket)
        assert state is not None and state.status == "finished"
        # The bot still acted on the turn that followed the per-hand
        # showdown event.
        assert socket.sent == [
            {
                "type": "action",
                "match_id": "m1",
                "action": "call",
                "turn_id": 4,
            }
        ]

    def test_match_ended_event_returns_final_state(self):
        runner = make_runner()
        socket = FakeWebSocket([{"type": "match_ended", "match_id": "m1"}])
        assert runner._message_loop(socket).status == "finished"

    def test_idle_recovery_returns_finished_state(self):
        runner = make_runner()
        socket = FakeWebSocket([])
        state = runner._message_loop(socket)
        assert state is not None and state.status == "finished"


class TestRecoveryFailureLimit:
    def test_persistent_state_errors_raise(self):
        runner = make_runner()

        def broken_fetch(*args, **kwargs):
            raise ws_module.PlayerSDKError("HTTP 404: Match not found")

        runner.client.fetch_latest_state = broken_fetch
        socket = FakeWebSocket([])
        with pytest.raises(
            ws_module.PlayerSDKError, match="check the match_id"
        ):
            runner._message_loop(socket)

    def test_success_resets_failure_counter(self):
        runner = make_runner()
        runner._recovery_failures = ws_module._MAX_RECOVERY_FAILURES - 1
        runner.client.fetch_latest_state = lambda *a, **k: running_state()
        assert runner._recover_missed_events() is None
        assert runner._recovery_failures == 0


class TestRunGuards:
    def test_missing_websockets_package_raises(self, monkeypatch):
        monkeypatch.setattr(ws_module, "_WEBSOCKETS_AVAILABLE", False)
        runner = make_runner()
        with pytest.raises(ws_module.RealtimeUnavailableError):
            runner.run()

    def test_close_code_4401_raises_auth_error(self, monkeypatch):
        runner = make_runner()
        runner.client.connect = lambda *a, **k: {"ok": True}

        def fake_connect(*args, **kwargs):
            raise ConnectionClosed(Close(4401, "Invalid API key"), None)

        monkeypatch.setattr(ws_module, "ws_connect", fake_connect)
        with pytest.raises(PlayerSDKAuthError):
            runner.run()


class TestWebsocketUrl:
    def test_http_becomes_ws_with_api_key_query(self):
        runner = make_runner()
        assert runner._websocket_url() == (
            "ws://127.0.0.1:8000/v1/ws?api_key=key"
        )

    def test_https_becomes_wss(self):
        runner = make_runner()
        runner.client.base_url = "https://poker.example.com"
        assert runner._websocket_url().startswith("wss://poker.example.com")
