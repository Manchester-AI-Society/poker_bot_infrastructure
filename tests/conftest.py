"""Shared fixtures for the player SDK test suite."""

from __future__ import annotations

import pytest

import player_sdk.config as config_module

POKER_ENV_KEYS = (
    "POKER_SERVER_URL",
    "POKER_API_KEY",
    "POKER_MATCH_ID",
    "POKER_PLAYER_ID",
    "POKER_TIMEOUT_SECONDS",
)


@pytest.fixture
def hermetic_env(monkeypatch):
    """Isolates tests from POKER_* env vars and any .env file."""
    for key in POKER_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(config_module, "load_dotenv", lambda: None)
    yield
