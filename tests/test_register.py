"""Self-service /v1/register endpoint."""

import asyncio

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from server.api.routers.bot_registry_routes import register
from server.api.shared_runtime_dependencies import require_player_id
from server.api_request_models import RegisterRequest


def call(name, code="letmein"):
    return asyncio.run(register(RegisterRequest(player_id=name, code=code)))


def status_of(name, code="letmein"):
    with pytest.raises(HTTPException) as err:
        call(name, code)
    return err.value.status_code


def test_disabled_without_code(monkeypatch):
    monkeypatch.delenv("REGISTRATION_CODE", raising=False)
    assert status_of("reg-off") == 403


def test_register_flow(monkeypatch):
    monkeypatch.setenv("REGISTRATION_CODE", "letmein")

    assert status_of("reg-alice", code="wrong") == 403
    with pytest.raises(ValidationError):
        RegisterRequest(player_id="bad name!")

    key = call("reg-alice")["api_key"]
    assert require_player_id(f"Bearer {key}", None) == "reg-alice"

    assert status_of("reg-alice") == 409  # names are one-shot
