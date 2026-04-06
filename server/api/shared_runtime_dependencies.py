from __future__ import annotations

from typing import Optional

from fastapi import HTTPException, status

from server.server_settings import load_api_keys
from server.websocket_connection_manager import ConnectionManager
from server.game import GameService


def extract_token(
    authorization: Optional[str], query_api_key: Optional[str]
) -> Optional[str]:
    """Extracts the API token from request metadata.

    Args:
        authorization (Optional[str]): Authorisation header value.
        query_api_key (Optional[str]): API key supplied in query parameters.

    Returns:
        Optional[str]: Extracted token value when available.
    """
    if authorization:
        parts = authorization.strip().split(" ", 1)
        if len(parts) == 2 and parts[0].lower() == "bearer":
            return parts[1].strip()
    if query_api_key:
        return query_api_key.strip()
    return None


api_keys = load_api_keys()
connections = ConnectionManager()
games = GameService()
games.set_event_handlers(
    broadcast_cb=connections.broadcast_to_players,
    direct_cb=connections.send_to_player,
)


def require_player_id(
    authorization: Optional[str],
    query_api_key: Optional[str],
) -> str:
    """Resolves and validates the player id for the current request.

    Args:
        authorization (Optional[str]): Authorisation header value.
        query_api_key (Optional[str]): API key supplied in query parameters.

    Returns:
        str: Player identifier mapped from a valid API key.
    """
    token = extract_token(authorization, query_api_key)
    if token is None or token not in api_keys:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
        )
    return api_keys[token]
