"""Tests for the play() entrypoint and bot file loading."""

from __future__ import annotations

import inspect

import pytest

import player_sdk._run as run_module
from player_sdk import PlayerConfig, play, run_bot
from player_sdk._ws import RealtimeUnavailableError
from player_sdk.bot_interface import PokerBot
from player_sdk.models import GameState

BOT_SOURCE = """
from player_sdk.bot_interface import PokerBot
from player_sdk.models import Action, GameState


class TempBot(PokerBot):
    def act(self, game_state: GameState) -> Action:
        return Action.fold()
"""


def sentinel_state() -> GameState:
    return GameState(
        hole_cards=(),
        community_cards=(),
        pot_size=0,
        stack_sizes=(1100, 900),
        current_bets=(0, 0),
        current_player_index=0,
        call_amount=0,
        minimum_raise=0,
        action_history=(),
        status="finished",
        player_ids=("p1", "p2"),
    )


class TestPlayValidation:
    def test_invalid_transport_raises(self, hermetic_env):
        with pytest.raises(ValueError, match="transport"):
            play(
                model=None,  # type: ignore[arg-type]
                api_key="k",
                server_url="http://127.0.0.1:8000",
                match_id="m1",
                transport="carrier-pigeon",
            )

    def test_api_key_server_url_match_id_are_mandatory(self):
        signature = inspect.signature(play)
        for name in ("api_key", "server_url", "match_id"):
            parameter = signature.parameters[name]
            assert parameter.default is inspect.Parameter.empty, name

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"api_key": "", "server_url": "http://s", "match_id": "m"},
            {"api_key": "k", "server_url": "  ", "match_id": "m"},
            {"api_key": "k", "server_url": "http://s", "match_id": ""},
        ],
    )
    def test_empty_mandatory_argument_raises(self, hermetic_env, kwargs):
        with pytest.raises(ValueError, match="mandatory"):
            play(model=None, **kwargs)  # type: ignore[arg-type]

    def test_missing_kwarg_raises_type_error(self, hermetic_env):
        with pytest.raises(TypeError):
            play(
                model=None,  # type: ignore[arg-type]
                api_key="k",
                server_url="http://127.0.0.1:8000",
            )


class TestPlayDispatch:
    def test_websocket_success_skips_http(self, hermetic_env, monkeypatch):
        calls = {"ws": False, "http": False}
        state = sentinel_state()

        class StubRunner:
            def __init__(self, **kwargs):
                pass

            def run(self):
                calls["ws"] = True
                return state

        monkeypatch.setattr(run_module, "RealtimeBotRunner", StubRunner)
        monkeypatch.setattr(
            run_module,
            "_run_over_http",
            lambda *a, **k: calls.__setitem__("http", True),
        )
        assert (
            play(
                model=None,  # type: ignore[arg-type]
                api_key="k",
                server_url="http://127.0.0.1:8000",
                match_id="m1",
            )
            is state
        )
        assert calls == {"ws": True, "http": False}

    def test_auto_falls_back_to_http_on_ws_failure(
        self, hermetic_env, monkeypatch
    ):
        calls = {"http": False}

        class StubRunner:
            def __init__(self, **kwargs):
                pass

            def run(self):
                raise RealtimeUnavailableError("no ws here")

        monkeypatch.setattr(run_module, "RealtimeBotRunner", StubRunner)

        def fake_http(bot, config, *, poll_interval_seconds, verbose):
            calls["http"] = True
            return sentinel_state()

        monkeypatch.setattr(run_module, "_run_over_http", fake_http)
        result = play(
            model=None,  # type: ignore[arg-type]
            api_key="k",
            server_url="http://127.0.0.1:8000",
            match_id="m1",
            verbose=False,
        )
        assert result is not None and result.status == "finished"
        assert calls["http"] is True

    def test_ws_transport_propagates_failure(self, hermetic_env, monkeypatch):
        class StubRunner:
            def __init__(self, **kwargs):
                pass

            def run(self):
                raise RealtimeUnavailableError("no ws here")

        monkeypatch.setattr(run_module, "RealtimeBotRunner", StubRunner)
        with pytest.raises(RealtimeUnavailableError):
            play(
                model=None,  # type: ignore[arg-type]
                api_key="k",
                server_url="http://127.0.0.1:8000",
                match_id="m1",
                transport="ws",
                verbose=False,
            )

    def test_forced_http_skips_ws(self, hermetic_env, monkeypatch):
        calls = {"ws": False}

        class StubRunner:
            def __init__(self, **kwargs):
                calls["ws"] = True

        monkeypatch.setattr(run_module, "RealtimeBotRunner", StubRunner)
        monkeypatch.setattr(
            run_module,
            "_run_over_http",
            lambda *a, **k: sentinel_state(),
        )
        play(
            model=None,  # type: ignore[arg-type]
            api_key="k",
            server_url="http://127.0.0.1:8000",
            match_id="m1",
            transport="http",
            verbose=False,
        )
        assert calls["ws"] is False


class TestRunBotBackCompat:
    def test_config_parameter_still_accepted(self, hermetic_env, monkeypatch):
        state = sentinel_state()
        monkeypatch.setattr(
            run_module,
            "_run_over_http",
            lambda *a, **k: state,
        )
        result = run_bot(
            bot=None,  # type: ignore[arg-type]
            config=PlayerConfig(base_url="http://127.0.0.1:8000", api_key="k"),
            transport="http",
            verbose=False,
        )
        assert result is state


class TestLoadBotFromFile:
    def test_loads_single_bot_class(self, tmp_path):
        bot_file = tmp_path / "temp_bot.py"
        bot_file.write_text(BOT_SOURCE)
        bot = run_module.load_bot_from_file(bot_file)
        assert isinstance(bot, PokerBot)

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            run_module.load_bot_from_file(tmp_path / "nope.py")

    def test_no_bot_class_raises(self, tmp_path):
        bot_file = tmp_path / "empty.py"
        bot_file.write_text("x = 1\n")
        with pytest.raises(RuntimeError, match="exactly one"):
            run_module.load_bot_from_file(bot_file)

    def test_multiple_bot_classes_raise(self, tmp_path):
        bot_file = tmp_path / "two_bots.py"
        bot_file.write_text(
            BOT_SOURCE + "\n\n" + BOT_SOURCE.replace("TempBot", "TempBot2")
        )
        with pytest.raises(RuntimeError, match="exactly one"):
            run_module.load_bot_from_file(bot_file)
