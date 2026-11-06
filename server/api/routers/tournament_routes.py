from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Header, HTTPException, status

from game import MatchStateError
from server.api.shared_runtime_dependencies import (
    api_keys,
    connections,
    require_admin_id,
    tournament,
)
from server.api_request_models import TournamentStartRequest

router = APIRouter(prefix="/v1", tags=["tournament"])


def _lobby() -> list[str]:
    """Bots with a live websocket whose key is still registered."""
    registered = set(api_keys.values())
    return [pid for pid in connections.connected_ids() if pid in registered]


@router.get("/lobby")
async def get_lobby() -> dict:
    """Lists bots currently connected and eligible to be seated."""
    return {"players": _lobby()}


@router.get("/tournament")
async def get_tournament() -> dict:
    """Returns the current tournament bracket."""
    return tournament.snapshot()


@router.post("/tournament/start")
async def start_tournament(
    request: TournamentStartRequest,
    authorization: Optional[str] = Header(default=None),
    x_admin_key: Optional[str] = Header(default=None),
) -> dict:
    """Seats every connected bot and starts round 1."""
    require_admin_id(authorization, x_admin_key)
    if request.small_blind >= request.big_blind:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="big_blind must be larger than small_blind",
        )
    try:
        await tournament.start(_lobby(), **request.model_dump())
    except MatchStateError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    return tournament.snapshot()
