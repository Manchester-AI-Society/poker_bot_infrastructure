from __future__ import annotations

from typing import Optional

from fastapi import (
    FastAPI,
    Header,
    HTTPException,
    Query,
    WebSocket,
    WebSocketDisconnect,
    status,
)

from server.config import load_api_keys
from server.connection_manager import ConnectionManager
from server.game import (
    GameService,
    InvalidActionError,
    MatchNotFoundError,
    MatchStateError,
)
from server.schemas import CreateMatchRequest, SubmitActionRequest


def _extract_token(
    authorization: Optional[str], query_api_key: Optional[str]
) -> Optional[str]:
    if authorization:
        parts = authorization.strip().split(" ", 1)
        if len(parts) == 2 and parts[0].lower() == "bearer":
            return parts[1].strip()
    if query_api_key:
        return query_api_key.strip()
    return None


app = FastAPI(title="Poker Bot Competition API", version="0.1.0")
api_keys = load_api_keys()
connections = ConnectionManager()
games = GameService()
games.set_event_handlers(
    broadcast_cb=connections.broadcast_to_players,
    direct_cb=connections.send_to_player,
)


@app.get("/health")
async def health() -> dict:
    return {"ok": True}


@app.get("/v1/bots")
async def list_bots() -> dict:
    return {"bots": list(api_keys.values())}


@app.get("/v1/matches")
async def list_matches() -> dict:
    return {"matches": games.list_matches()}


@app.post("/v1/matches")
async def create_match(request: CreateMatchRequest) -> dict:
    try:
        match = games.create_match(request)
    except MatchStateError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc

    return {
        "match_id": match.match_id,
        "status": match.status,
        "event_log_limit": match.event_log_limit,
        "state": games.get_public_state(match.match_id),
    }


@app.post("/v1/matches/{match_id}/start")
async def start_match(match_id: str) -> dict:
    try:
        await games.start_match(match_id)
    except MatchNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Match not found"
        ) from exc
    except MatchStateError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc

    return {"match_id": match_id, "status": "running"}


@app.get("/v1/matches/{match_id}")
async def get_match_state(
    match_id: str, viewer_id: Optional[str] = Query(default=None)
) -> dict:
    try:
        state = games.get_public_state(match_id, viewer_id=viewer_id)
    except MatchNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Match not found"
        ) from exc

    return {"match_id": match_id, "state": state}


@app.get("/v1/matches/{match_id}/events")
async def get_match_events(
    match_id: str,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=1000),
) -> dict:
    try:
        payload = games.get_logs_page(match_id, offset=offset, limit=limit)
    except MatchNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Match not found"
        ) from exc
    return {"match_id": match_id, **payload}


@app.post("/v1/matches/{match_id}/actions")
async def submit_action_http(
    match_id: str, request: SubmitActionRequest
) -> dict:
    if not request.player_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="player_id is required",
        )

    try:
        await games.submit_action(
            match_id=match_id,
            player_id=request.player_id,
            action=request.action,
            amount=request.amount,
            turn_id=request.turn_id,
        )
    except MatchNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Match not found"
        ) from exc
    except (MatchStateError, InvalidActionError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc

    return {"ok": True}


@app.post("/v1/matches/{match_id}/actions/self")
async def submit_action_self(
    match_id: str,
    request: SubmitActionRequest,
    authorization: Optional[str] = Header(default=None),
    x_api_key: Optional[str] = Header(default=None),
) -> dict:
    token = _extract_token(authorization, x_api_key)
    if token is None or token not in api_keys:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key"
        )
    player_id = api_keys[token]

    try:
        await games.submit_action(
            match_id=match_id,
            player_id=player_id,
            action=request.action,
            amount=request.amount,
            turn_id=request.turn_id,
        )
    except MatchNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Match not found"
        ) from exc
    except (MatchStateError, InvalidActionError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc

    return {"ok": True}


@app.websocket("/v1/ws")
async def websocket_gateway(
    websocket: WebSocket, api_key: Optional[str] = Query(default=None)
) -> None:
    token = _extract_token(websocket.headers.get("authorization"), api_key)
    if token is None or token not in api_keys:
        await websocket.close(code=4401, reason="Invalid API key")
        return

    player_id = api_keys[token]
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
                        "error": "Unsupported message type. Expected 'action'.",
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


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("server.main:app", host="0.0.0.0", port=8000, reload=True)
