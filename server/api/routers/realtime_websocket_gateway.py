from __future__ import annotations

from typing import Optional

from fastapi import (
    APIRouter,
    HTTPException,
    Query,
    WebSocket,
    WebSocketDisconnect,
)

from game import InvalidActionError, MatchNotFoundError, MatchStateError
from server.api.shared_runtime_dependencies import (
    connections,
    games,
    require_player_id,
)

router = APIRouter(tags=["websocket"])


@router.websocket("/v1/ws")
async def websocket_gateway(
    websocket: WebSocket, api_key: Optional[str] = Query(default=None)
) -> None:
    """Handles realtime game messages over a WebSocket connection.

    Args:
        websocket (WebSocket): Active websocket connection.
        api_key (Optional[str]): Optional API key query parameter.

    Returns:
        None: This function does not return a value.
    """
    try:
        player_id = require_player_id(
            websocket.headers.get("authorization"), api_key
        )
    except HTTPException:
        await websocket.close(code=4401, reason="Invalid API key")
        return

    await connections.connect(player_id, websocket)
    await connections.send_to_player(
        player_id, {"type": "connected", "player_id": player_id}
    )

    try:
        while True:
            payload = await websocket.receive_json()
            if payload.get("type") != "action":
                await connections.send_to_player(
                    player_id,
                    {
                        "type": "error",
                        "error": (
                            "Unsupported message type. Expected 'action'."
                        ),
                    },
                )
                continue

            match_id = payload.get("match_id")
            action = payload.get("action")
            amount = payload.get("amount")
            turn_id = payload.get("turn_id")
            if not match_id or not action:
                await connections.send_to_player(
                    player_id,
                    {
                        "type": "error",
                        "error": "action payload requires match_id and action",
                    },
                )
                continue

            try:
                await games.submit_action(
                    match_id=match_id,
                    player_id=player_id,
                    action=str(action),
                    amount=amount,
                    turn_id=turn_id,
                )
            except (
                MatchNotFoundError,
                MatchStateError,
                InvalidActionError,
            ) as exc:
                await connections.send_to_player(
                    player_id, {"type": "error", "error": str(exc)}
                )
    except WebSocketDisconnect:
        await connections.disconnect(player_id)
