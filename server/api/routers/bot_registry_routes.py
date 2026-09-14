from __future__ import annotations

import secrets
from typing import Dict, List, Optional

from fastapi import APIRouter, Header

from server.api.shared_runtime_dependencies import (
    api_keys,
    require_admin_id,
    require_player_id,
)
from server.api_request_models import (
    CreatePlayerRequest,
    RotatePlayerKeyRequest,
)

router = APIRouter(prefix="/v1", tags=["bots"])


@router.get("/bots")
async def list_bots() -> dict:
    """Lists all registered bot identifiers.

    Args:
        None: This function does not take external arguments.

    Returns:
        dict: Mapping containing the available bot identifiers.
    """
    return {"bots": list(api_keys.values())}


@router.get("/me")
async def whoami(
    authorization: Optional[str] = Header(default=None),
    x_api_key: Optional[str] = Header(default=None),
) -> dict:
    """Resolves the calling player's identity from their API key.

    Args:
        authorization (Optional[str]): Optional Bearer authorisation header.
        x_api_key (Optional[str]): Optional API key header value.

    Returns:
        dict: Mapping containing the resolved player identifier.
    """
    player_id = require_player_id(authorization, x_api_key)
    return {"player_id": player_id}


@router.post("/admin/players")
async def create_player(
    request: CreatePlayerRequest,
    authorization: Optional[str] = Header(default=None),
    x_admin_key: Optional[str] = Header(default=None),
) -> dict:
    """Creates a player and assigns an API key.

    Args:
        request (CreatePlayerRequest): Player creation payload.
        authorization (Optional[str]): Optional Bearer authorisation header.
        x_admin_key (Optional[str]): Optional admin API key header value.

    Returns:
        dict: Mapping containing the created player and API key.
    """
    require_admin_id(authorization, x_admin_key)

    if request.player_id in api_keys.values():
        return {"player_id": request.player_id, "created": False}

    api_key = request.api_key or secrets.token_urlsafe(24)
    api_keys[api_key] = request.player_id
    return {
        "player_id": request.player_id,
        "api_key": api_key,
        "created": True,
    }


@router.get("/admin/players")
async def list_players(
    authorization: Optional[str] = Header(default=None),
    x_admin_key: Optional[str] = Header(default=None),
) -> dict:
    """Lists players and their assigned API keys.

    Args:
        authorization (Optional[str]): Optional Bearer authorisation header.
        x_admin_key (Optional[str]): Optional admin API key header value.

    Returns:
        dict: Mapping containing player identifiers and API keys.
    """
    require_admin_id(authorization, x_admin_key)

    players: Dict[str, List[str]] = {}
    for api_key, player_id in api_keys.items():
        players.setdefault(player_id, []).append(api_key)
    return {"players": players}


@router.delete("/admin/players/{player_id}")
async def delete_player(
    player_id: str,
    authorization: Optional[str] = Header(default=None),
    x_admin_key: Optional[str] = Header(default=None),
) -> dict:
    """Deletes a player and revokes all mapped API keys.

    Args:
        player_id (str): Player identifier.
        authorization (Optional[str]): Optional Bearer authorisation header.
        x_admin_key (Optional[str]): Optional admin API key header value.

    Returns:
        dict: Mapping containing deleted player details.
    """
    require_admin_id(authorization, x_admin_key)

    revoked_keys = [
        key for key, value in api_keys.items() if value == player_id
    ]
    for key in revoked_keys:
        del api_keys[key]

    return {
        "player_id": player_id,
        "deleted": len(revoked_keys) > 0,
        "revoked_keys": revoked_keys,
    }


@router.post("/admin/players/{player_id}/rotate-key")
async def rotate_player_key(
    player_id: str,
    request: RotatePlayerKeyRequest,
    authorization: Optional[str] = Header(default=None),
    x_admin_key: Optional[str] = Header(default=None),
) -> dict:
    """Rotates the API key for a player.

    Args:
        player_id (str): Player identifier.
        request (RotatePlayerKeyRequest): Key rotation payload.
        authorization (Optional[str]): Optional Bearer authorisation header.
        x_admin_key (Optional[str]): Optional admin API key header value.

    Returns:
        dict: Mapping containing old and new key details.
    """
    require_admin_id(authorization, x_admin_key)

    old_keys = [key for key, value in api_keys.items() if value == player_id]
    for key in old_keys:
        del api_keys[key]

    new_key = request.api_key or secrets.token_urlsafe(24)
    api_keys[new_key] = player_id

    return {
        "player_id": player_id,
        "old_keys": old_keys,
        "new_key": new_key,
    }
