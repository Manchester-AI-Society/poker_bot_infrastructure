from __future__ import annotations

import json
import time
import urllib.parse
from typing import Any, Dict, Mapping, Optional

from ._http import (
    PlayerSDKAuthError,
    PlayerSDKBadRequestError,
    PlayerSDKError,
)
from .bot_interface import PokerBot
from .client import PokerEngineClient, find_player_index, translate_action
from .models import Action, GameState

try:
    from websockets.exceptions import ConnectionClosed, InvalidHandshake
    from websockets.sync.client import connect as ws_connect

    _WEBSOCKETS_AVAILABLE = True
except ImportError:  # pragma: no cover - depends on install
    _WEBSOCKETS_AVAILABLE = False

_TERMINAL_EVENTS = frozenset({"showdown", "match_ended"})
_TERMINAL_STATUSES = frozenset({"finished"})
_MAX_BACKOFF_SECONDS = 10.0
_IDLE_CHECK_SECONDS = 5.0
_MAX_RECOVERY_FAILURES = 5


class RealtimeUnavailableError(PlayerSDKError):
    """Raised when the websocket transport cannot be established."""


class RealtimeBotRunner:
    """Runs a bot over the realtime websocket gateway.

    HTTP is used only for the health check, match discovery, missed
    turn recovery, and the final state fetch; turns arrive as pushed
    ``your_turn`` messages and actions are sent on the same socket.
    """

    def __init__(
        self,
        *,
        base_url: str,
        match_id: str,
        bot: PokerBot,
        player_id: Optional[str] = None,
        api_key: Optional[str] = None,
        timeout_seconds: float = 10.0,
        verbose: bool = True,
    ) -> None:
        """Stores connection settings for the realtime runner.

        Args:
            base_url (str): Server base URL.
            match_id (str): Match identifier, may be empty for
                auto-discovery.
            bot (PokerBot): Bot instance that provides actions.
            player_id (Optional[str]): Explicit player identity.
            api_key (Optional[str]): Bot API key.
            timeout_seconds (float): HTTP request timeout.
            verbose (bool): Prints progress when True.
        """
        self.verbose = verbose
        self.client = PokerEngineClient(
            base_url=base_url,
            match_id=match_id,
            bot=bot,
            player_id=player_id,
            api_key=api_key,
            timeout_seconds=timeout_seconds,
        )
        self._established = False
        self._recovery_failures = 0

    def run(self) -> Optional[GameState]:
        """Plays the match over websocket until it finishes.

        Returns:
            Optional[GameState]: Final game state once the match
            finishes.

        Raises:
            RealtimeUnavailableError: When the websocket transport
                cannot be established.
            PlayerSDKAuthError: When the API key is rejected.
        """
        if not _WEBSOCKETS_AVAILABLE:
            raise RealtimeUnavailableError(
                "The websocket transport requires the 'websockets'"
                " package; install it or use transport='http'."
            )

        client = self.client
        health = client.connect()
        if not health.get("ok"):
            raise RuntimeError("Server health check failed")
        client.resolve_identity()
        if not client.match_id:
            client.discover_match()

        if self.verbose:
            print(f"[player_sdk] Playing as {client.player_id} (websocket)")
            print(f"[player_sdk] Match: {client.match_id}")

        ws_url = self._websocket_url()
        backoff = 1.0
        while True:
            try:
                with ws_connect(ws_url, close_timeout=5) as websocket:
                    self._established = True
                    backoff = 1.0
                    return self._message_loop(websocket)
            except ConnectionClosed as exc:
                received = getattr(exc, "rcvd", None)
                if received is not None and received.code == 4401:
                    raise PlayerSDKAuthError("Invalid API key") from exc
                self._warn("connection lost; reconnecting...")
            except (InvalidHandshake, OSError, TimeoutError) as exc:
                if not self._established:
                    raise RealtimeUnavailableError(str(exc)) from exc
                self._warn(f"connection error ({exc}); reconnecting...")
            time.sleep(backoff)
            backoff = min(backoff * 2, _MAX_BACKOFF_SECONDS)

    def _message_loop(self, websocket: Any) -> Optional[GameState]:
        while True:
            try:
                raw = websocket.recv(timeout=_IDLE_CHECK_SECONDS)
            except TimeoutError:
                state = self._recover_missed_events()
                if state is not None:
                    return state
                continue

            message = json.loads(raw)
            if not isinstance(message, dict):
                continue
            self._recovery_failures = 0
            kind = message.get("type")

            if kind == "your_turn":
                state = self._handle_your_turn(websocket, message)
                if state is not None:
                    return state
            elif kind in _TERMINAL_EVENTS:
                return self._final_state()
            elif kind == "error":
                self._warn(f"server: {message.get('error')}")
            elif kind == "timeout" and self.verbose:
                print(
                    "[player_sdk] Turn timed out for"
                    f" {message.get('player_id')}"
                )

    def _handle_your_turn(
        self, websocket: Any, message: Mapping[str, Any]
    ) -> Optional[GameState]:
        raw_state = message.get("state")
        if not isinstance(raw_state, Mapping):
            return None

        self._discover_seat(raw_state)
        payload: Dict[str, Any] = {
            "match_id": message.get("match_id", self.client.match_id),
            "state": dict(raw_state),
            "action_history": self._safe_history(),
        }
        state = self.client.receive_game_state(payload)
        if state.status in _TERMINAL_STATUSES:
            return self._final_state()

        action = self.client.bot.act(state)
        if not isinstance(action, Action):
            raise TypeError("PokerBot.act must return an Action")

        engine_action, amount = translate_action(action, state)
        outgoing: Dict[str, Any] = {
            "type": "action",
            "match_id": self.client.match_id,
            "action": engine_action,
        }
        if amount is not None:
            outgoing["amount"] = amount
        if state.turn_id is not None and state.turn_id >= 1:
            outgoing["turn_id"] = state.turn_id
        websocket.send(json.dumps(outgoing))
        return None

    def _recover_missed_events(self) -> Optional[GameState]:
        try:
            state = self.client.fetch_latest_state()
            if state.status in _TERMINAL_STATUSES:
                return state
            if self.client.is_bot_turn(state):
                self.client.maybe_act_on_current_state()
        except PlayerSDKBadRequestError:
            pass
        except PlayerSDKAuthError:
            raise
        except PlayerSDKError as exc:
            self._recovery_failures += 1
            if self._recovery_failures >= _MAX_RECOVERY_FAILURES:
                raise PlayerSDKError(
                    "Unable to read match"
                    f" {self.client.match_id!r} after"
                    f" {self._recovery_failures} attempts"
                    f" ({exc}); check the match_id and server URL."
                ) from exc
        else:
            self._recovery_failures = 0
        return None

    def _final_state(self) -> Optional[GameState]:
        try:
            return self.client.fetch_state_snapshot()
        except PlayerSDKError:
            return self.client.last_state

    def _safe_history(self) -> list[dict]:
        try:
            return self.client.fetch_action_history()
        except PlayerSDKError:
            return []

    def _discover_seat(self, raw_state: Mapping[str, Any]) -> None:
        if self.client.player_index is not None:
            return
        index = find_player_index(
            raw_state.get("players"), self.client.player_id
        )
        if index is not None:
            self.client.player_index = index

    def _websocket_url(self) -> str:
        parsed = urllib.parse.urlparse(self.client.base_url)
        scheme = "wss" if parsed.scheme == "https" else "ws"
        query = urllib.parse.urlencode({"api_key": self.client.api_key or ""})
        return f"{scheme}://{parsed.netloc}/v1/ws?{query}"

    def _warn(self, text: str) -> None:
        if self.verbose:
            print(f"[player_sdk] {text}")
