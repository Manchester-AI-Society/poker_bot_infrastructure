from __future__ import annotations

from typing import Optional

from fastapi import HTTPException, status

from game import GameService
from server.server_settings import load_admin_api_keys, load_api_keys
from server.websocket_connection_manager import ConnectionManager


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


def _resolve_identity(
    token: Optional[str], key_mapping: dict, error_message: str
) -> str:
    """Resolves an identity from a key mapping.

    Args:
        token (Optional[str]): Candidate token extracted from the request.
        key_mapping (dict): Mapping from API key to identity.
        error_message (str): Error message for failed authentication.

    Returns:
        str: Identity mapped from the token.
    """
    if token is None or token not in key_mapping:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=error_message,
        )
    return key_mapping[token]


api_keys = load_api_keys()
admin_api_keys = load_admin_api_keys()
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
    return _resolve_identity(token, api_keys, "Invalid API key")


def require_admin_id(
    authorization: Optional[str],
    query_api_key: Optional[str],
) -> str:
    """Resolves and validates the admin id for privileged requests.

    Args:
        authorization (Optional[str]): Authorisation header value.
        query_api_key (Optional[str]): API key supplied via header or query.

    Returns:
        str: Admin identifier mapped from a valid admin API key.
    """
    token = extract_token(authorization, query_api_key)
    return _resolve_identity(token, admin_api_keys, "Invalid admin API key")
