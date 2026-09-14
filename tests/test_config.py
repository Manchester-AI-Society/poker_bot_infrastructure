"""Tests for PlayerConfig resolution order and error messages."""

from __future__ import annotations

import pytest

from player_sdk import PlayerConfig


class TestFromEnvironment:
    def test_explicit_kwargs_win(self, hermetic_env):
        config = PlayerConfig.from_environment(
            base_url="http://example:9000",
            api_key="kwarg-key",
            match_id="m1",
            player_id="p1",
            timeout_seconds=3.5,
        )
        assert config.base_url == "http://example:9000"
        assert config.api_key == "kwarg-key"
        assert config.match_id == "m1"
        assert config.player_id == "p1"
        assert config.timeout_seconds == 3.5

    def test_env_vars_fill_missing_kwargs(self, hermetic_env, monkeypatch):
        monkeypatch.setenv("POKER_SERVER_URL", "http://env:8000")
        monkeypatch.setenv("POKER_API_KEY", "env-key")
        config = PlayerConfig.from_environment()
        assert config.base_url == "http://env:8000"
        assert config.api_key == "env-key"

    def test_kwargs_override_env_vars(self, hermetic_env, monkeypatch):
        monkeypatch.setenv("POKER_API_KEY", "env-key")
        config = PlayerConfig.from_environment(api_key="kwarg-key")
        assert config.api_key == "kwarg-key"

    def test_default_base_url(self, hermetic_env):
        config = PlayerConfig.from_environment(api_key="k")
        assert config.base_url == "http://127.0.0.1:8000"

    def test_missing_api_key_raises_openai_style_error(self, hermetic_env):
        with pytest.raises(ValueError) as excinfo:
            PlayerConfig.from_environment()
        message = str(excinfo.value)
        assert "api_key option must be set" in message
        assert "POKER_API_KEY" in message

    def test_timeout_from_env(self, hermetic_env, monkeypatch):
        monkeypatch.setenv("POKER_TIMEOUT_SECONDS", "4.25")
        config = PlayerConfig.from_environment(api_key="k")
        assert config.timeout_seconds == 4.25

    def test_bad_timeout_falls_back_to_default(
        self, hermetic_env, monkeypatch
    ):
        monkeypatch.setenv("POKER_TIMEOUT_SECONDS", "not-a-number")
        config = PlayerConfig.from_environment(api_key="k")
        assert config.timeout_seconds == 10.0

    def test_explicit_timeout_beats_env(self, hermetic_env, monkeypatch):
        monkeypatch.setenv("POKER_TIMEOUT_SECONDS", "4.0")
        config = PlayerConfig.from_environment(
            api_key="k", timeout_seconds=7.5
        )
        assert config.timeout_seconds == 7.5

    def test_blank_match_id_becomes_none(self, hermetic_env, monkeypatch):
        monkeypatch.setenv("POKER_MATCH_ID", "   ")
        config = PlayerConfig.from_environment(api_key="k")
        assert config.match_id is None
