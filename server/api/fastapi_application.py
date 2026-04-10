from __future__ import annotations

from fastapi import FastAPI

from server.api.routers.bot_registry_routes import router as bots_router
from server.api.routers.health_status_routes import router as health_router
from server.api.routers.match_management_routes import (
    router as matches_router,
)
from server.api.routers.realtime_websocket_gateway import (
    router as websocket_router,
)


def create_app() -> FastAPI:
    """Creates and configures the FastAPI application.

    Args:
        None: This function does not take external arguments.

    Returns:
        FastAPI: Application instance configured with routes.
    """
    app = FastAPI(title="Poker Bot Competition API", version="0.1.0")
    app.include_router(health_router)
    app.include_router(bots_router)
    app.include_router(matches_router)
    app.include_router(websocket_router)
    return app


app = create_app()
