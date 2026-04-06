from __future__ import annotations

from fastapi import APIRouter

from server.api.shared_runtime_dependencies import api_keys


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
