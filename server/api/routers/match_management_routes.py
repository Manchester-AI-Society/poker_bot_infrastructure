from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Query, status

from server.api.shared_runtime_dependencies import (
    games,
    require_admin_id,
    require_player_id,
)
from game import InvalidActionError, MatchNotFoundError, MatchStateError
from server.api_request_models import (
    CreateMatchRequest,
    EndMatchRequest,
    PauseMatchRequest,
    ResumeMatchRequest,
    SubmitActionRequest,
)


router = APIRouter(prefix="/v1", tags=["matches"])


@router.get("/matches")
async def list_matches() -> dict:
    """Lists all available matches.

    Args:
        None: This function does not take external arguments.

    Returns:
        dict: Mapping containing the available matches.
    """
    return {"matches": games.list_matches()}


@router.post("/matches")
async def create_match(
    request: CreateMatchRequest,
    authorization: Optional[str] = Header(default=None),
    x_admin_key: Optional[str] = Header(default=None),
) -> dict:
    """Creates a new poker match.

    Args:
        request (CreateMatchRequest): Match creation payload.

    Returns:
        dict: Mapping containing the created match metadata and state.
    """
    require_admin_id(authorization, x_admin_key)

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


@router.post("/matches/{match_id}/start")
async def start_match(
    match_id: str,
    authorization: Optional[str] = Header(default=None),
    x_admin_key: Optional[str] = Header(default=None),
) -> dict:
    """Starts an existing match.

    Args:
        match_id (str): Match identifier.

    Returns:
        dict: Mapping containing the started match status.
    """
    require_admin_id(authorization, x_admin_key)

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


@router.get("/matches/{match_id}")
async def get_match_state(
    match_id: str, viewer_id: Optional[str] = Query(default=None)
) -> dict:
    """Gets the public state for a match.

    Args:
        match_id (str): Match identifier.
        viewer_id (Optional[str]): Optional player identifier for private view data.

    Returns:
        dict: Mapping containing the current match state.
    """
    try:
        state = games.get_public_state(match_id, viewer_id=viewer_id)
    except MatchNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Match not found"
        ) from exc

    return {"match_id": match_id, "state": state}


@router.get("/matches/{match_id}/events")
async def get_match_events(
    match_id: str,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=1000),
) -> dict:
    """Gets paged events for a match.

    Args:
        match_id (str): Match identifier.
        offset (int): Zero-based event offset.
        limit (int): Maximum number of events to return.

    Returns:
        dict: Mapping containing paged event data.
    """
    try:
        payload = games.get_logs_page(match_id, offset=offset, limit=limit)
    except MatchNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Match not found"
        ) from exc
    return {"match_id": match_id, **payload}


@router.post("/matches/{match_id}/actions")
async def submit_action_http(
    match_id: str, request: SubmitActionRequest
) -> dict:
    """Submits an action on behalf of a player id in the request body.

    Args:
        match_id (str): Match identifier.
        request (SubmitActionRequest): Action payload.

    Returns:
        dict: Mapping indicating whether submission succeeded.
    """
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


@router.post("/matches/{match_id}/pause")
async def pause_match(
    match_id: str,
    request: PauseMatchRequest,
    authorization: Optional[str] = Header(default=None),
    x_admin_key: Optional[str] = Header(default=None),
) -> dict:
    """Pauses a running match by admin command.

    Args:
        match_id (str): Match identifier.
        request (PauseMatchRequest): Pause command payload.
        authorization (Optional[str]): Optional Bearer authorisation header.
        x_admin_key (Optional[str]): Optional admin API key header value.

    Returns:
        dict: Mapping containing pause command results.
    """
    admin_id = require_admin_id(authorization, x_admin_key)

    try:
        return await games.pause_match(match_id, admin_id, request.reason)
    except MatchNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Match not found"
        ) from exc
    except MatchStateError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc


@router.post("/matches/{match_id}/resume")
async def resume_match(
    match_id: str,
    request: ResumeMatchRequest,
    authorization: Optional[str] = Header(default=None),
    x_admin_key: Optional[str] = Header(default=None),
) -> dict:
    """Resumes a paused match by admin command.

    Args:
        match_id (str): Match identifier.
        request (ResumeMatchRequest): Resume command payload.
        authorization (Optional[str]): Optional Bearer authorisation header.
        x_admin_key (Optional[str]): Optional admin API key header value.

    Returns:
        dict: Mapping containing resume command results.
    """
    admin_id = require_admin_id(authorization, x_admin_key)

    try:
        return await games.resume_match(match_id, admin_id, request.reason)
    except MatchNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Match not found"
        ) from exc
    except MatchStateError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc


@router.post("/matches/{match_id}/end")
async def end_match(
    match_id: str,
    request: EndMatchRequest,
    authorization: Optional[str] = Header(default=None),
    x_admin_key: Optional[str] = Header(default=None),
) -> dict:
    """Ends an active match by admin command.

    Args:
        match_id (str): Match identifier.
        request (EndMatchRequest): End command payload.
        authorization (Optional[str]): Optional Bearer authorisation header.
        x_admin_key (Optional[str]): Optional admin API key header value.

    Returns:
        dict: Mapping containing end command results.
    """
    admin_id = require_admin_id(authorization, x_admin_key)

    try:
        return await games.end_match(
            match_id,
            admin_id,
            request.reason,
            request.mode,
        )
    except MatchNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Match not found"
        ) from exc
    except MatchStateError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc


@router.get("/matches/{match_id}/full-state")
async def get_match_full_state(
    match_id: str,
    authorization: Optional[str] = Header(default=None),
    x_admin_key: Optional[str] = Header(default=None),
) -> dict:
    """Gets the full private state for admin inspection.

    Args:
        match_id (str): Match identifier.
        authorization (Optional[str]): Optional Bearer authorisation header.
        x_admin_key (Optional[str]): Optional admin API key header value.

    Returns:
        dict: Mapping containing full private state for the match.
    """
    require_admin_id(authorization, x_admin_key)

    try:
        state = games.get_full_state_for_admin(match_id)
    except MatchNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Match not found"
        ) from exc

    return {"match_id": match_id, "state": state}


@router.get("/matches/{match_id}/admin-actions")
async def get_match_admin_actions(
    match_id: str,
    authorization: Optional[str] = Header(default=None),
    x_admin_key: Optional[str] = Header(default=None),
) -> dict:
    """Gets the admin action history for a match.

    Args:
        match_id (str): Match identifier.
        authorization (Optional[str]): Optional Bearer authorisation header.
        x_admin_key (Optional[str]): Optional admin API key header value.

    Returns:
        dict: Mapping containing admin action entries for the match.
    """
    require_admin_id(authorization, x_admin_key)

    try:
        actions = games.get_admin_actions(match_id)
    except MatchNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Match not found"
        ) from exc

    return {"match_id": match_id, "admin_actions": actions}


@router.post("/matches/{match_id}/actions/self")
async def submit_action_self(
    match_id: str,
    request: SubmitActionRequest,
    authorization: Optional[str] = Header(default=None),
    x_api_key: Optional[str] = Header(default=None),
) -> dict:
    """Submits an action for the authenticated player.

    Args:
        match_id (str): Match identifier.
        request (SubmitActionRequest): Action payload.
        authorization (Optional[str]): Optional Bearer authorisation header.
        x_api_key (Optional[str]): Optional API key header value.

    Returns:
        dict: Mapping indicating whether submission succeeded.
    """
    player_id = require_player_id(authorization, x_api_key)

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
