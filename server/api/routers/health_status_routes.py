from __future__ import annotations

from fastapi import APIRouter


router = APIRouter()


@router.get("/health")
async def health() -> dict:
    """Checks the health status of the API.

    Args:
        None: This function does not take external arguments.

    Returns:
        dict: Mapping containing the service health status.
    """
    return {"ok": True}
