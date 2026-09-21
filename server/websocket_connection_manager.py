import asyncio
import logging
from typing import Dict, Iterable, List, Tuple

from fastapi import WebSocket

LOGGER = logging.getLogger(__name__)


class ConnectionManager:
    def __init__(self) -> None:
        """Initialises the connection manager.

        Args:
            None: This function does not take external arguments.

        Returns:
            None: This function does not return a value.
        """
        self._connections: Dict[str, WebSocket] = {}
        self._lock = asyncio.Lock()

    async def connect(self, player_id: str, websocket: WebSocket) -> None:
        """Connects a player to the game.

        Args:
            player_id (str): Identifier for player.
            websocket (WebSocket): Input value for websocket.

        Returns:
            None: This function does not return a value.
        """
        await websocket.accept()
        async with self._lock:
            self._connections[player_id] = websocket

    async def disconnect(self, player_id: str) -> None:
        """Disconnects a player from the game.

        Args:
            player_id (str): Identifier for player.

        Returns:
            None: This function does not return a value.
        """
        async with self._lock:
            self._connections.pop(player_id, None)

    def is_connected(self, player_id: str) -> bool:
        """Checks whether a player currently has a live socket.

        Args:
            player_id (str): Identifier for player.

        Returns:
            bool: True when the player has an active connection.
        """
        return player_id in self._connections

    def connected_ids(self) -> List[str]:
        """Returns the ids of all currently connected players.

        Args:
            None: This function does not take external arguments.

        Returns:
            List[str]: Player ids with live connections.
        """
        return list(self._connections.keys())

    async def send_to_player(self, player_id: str, payload: dict) -> None:
        """Sends a message to a specific player.

        Args:
            player_id (str): Identifier for player.
            payload (dict): Payload data used by this function.

        Returns:
            None: This function does not return a value.
        """
        async with self._lock:
            websocket = self._connections.get(player_id)
        if websocket is None:
            return
        try:
            await websocket.send_json(payload)
        except Exception:
            LOGGER.debug("Dropping dead websocket for player_id=%s", player_id)
            await self._disconnect_if_current(player_id, websocket)

    async def broadcast_to_players(
        self, player_ids: Iterable[str], payload: dict
    ) -> None:
        """Broadcasts a message to multiple players.

        Args:
            player_ids (Iterable[str]): Input value for player ids.
            payload (dict): Payload data used by this function.

        Returns:
            None: This function does not return a value.
        """
        targets: List[Tuple[str, WebSocket]] = []
        async with self._lock:
            for player_id in player_ids:
                websocket = self._connections.get(player_id)
                if websocket is not None:
                    targets.append((player_id, websocket))

        if not targets:
            return

        send_results = await asyncio.gather(
            *(websocket.send_json(payload) for _, websocket in targets),
            return_exceptions=True,
        )

        failed_targets = [
            (player_id, websocket)
            for (player_id, websocket), result in zip(targets, send_results)
            if isinstance(result, Exception)
        ]

        for player_id, websocket in failed_targets:
            LOGGER.debug(
                "Dropping dead websocket during broadcast for player_id=%s",
                player_id,
            )
            await self._disconnect_if_current(player_id, websocket)

    async def _disconnect_if_current(
        self, player_id: str, websocket: WebSocket
    ) -> None:
        """Disconnects a player if the provided websocket is the current one.

        Args:
            player_id (str): Identifier for player.
            websocket (WebSocket): Input value for websocket.

        Returns:
            None: This function does not return a value.
        """
        async with self._lock:
            current = self._connections.get(player_id)
            if current is websocket:
                self._connections.pop(player_id, None)
