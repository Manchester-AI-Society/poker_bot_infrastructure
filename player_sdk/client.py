from __future__ import annotations

import time
import urllib.parse
from typing import Any, Dict, Mapping, Optional, Tuple, Union

from ._http import (
    PlayerSDKAuthError,
    PlayerSDKBadRequestError,
    PlayerSDKError,
    http_json,
)
from .bot_interface import PokerBot
from .models import Action, ActionRecord, GameState
from .parser import GameStateParser

_TERMINAL_STATUSES = frozenset({"finished"})
_MAX_TRANSIENT_FAILURES = 5


def translate_action(
    action: Action, state: GameState
) -> Tuple[str, Optional[int]]:
    """Converts an SDK action to an engine action and amount.

    Args:
        action (Action): SDK action (fold/call/raise).
        state (GameState): State the action applies to.

    Returns:
        Tuple[str, Optional[int]]: Engine action name and optional amount.
    """
    if action.action_type == "fold":
        return "fold", None

    if action.action_type == "call":
        if state.call_amount == 0:
            return "check", None
        return "call", None

    if state.call_amount == 0:
        return "bet", action.amount
    return "raise_to", action.amount


def find_player_index(players: Any, player_id: Optional[str]) -> Optional[int]:
    """Returns the seat index of ``player_id`` in a players payload list."""
    if player_id is None or not isinstance(players, list):
        return None
    for index, player in enumerate(players):
        if isinstance(player, Mapping) and str(player.get("id")) == player_id:
            return index
    return None


class PokerEngineClient:
    """Minimal client that connects a bot to the running game engine.

    ``player_id`` and ``player_index`` are optional: the client resolves
    its identity from the API key via ``GET /v1/me`` and discovers its
    seat from the match players list on the first state fetch.
    """

    def __init__(
        self,
        *,
        base_url: str,
        match_id: str,
        bot: PokerBot,
        player_id: Optional[str] = None,
        player_index: Optional[int] = None,
        api_key: Optional[str] = None,
        parser: Optional[GameStateParser] = None,
        timeout_seconds: float = 10.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.match_id = match_id
        self.player_id = player_id
        self.player_index = player_index
        self.bot = bot
        self.parser = parser or GameStateParser()
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds

        self.connected = False
        self.last_state: Optional[GameState] = None

    def connect(self, api_key: Optional[str] = None) -> Dict[str, Any]:
        """Connects to the engine, storing an optional API key."""
        if api_key is not None:
            self.api_key = api_key
        health = self._request("GET", "/health")
        self.connected = bool(health.get("ok", False))
        return health

    def resolve_identity(self) -> str:
        """Resolves the player id for this client's API key via /v1/me."""
        if self.player_id is not None:
            return self.player_id
        if not self.api_key:
            raise RuntimeError(
                "Cannot resolve identity without an API key;"
                " pass player_id or api_key."
            )
        payload = self._request("GET", "/v1/me")
        player_id = payload.get("player_id")
        if not player_id:
            raise RuntimeError("Server did not return a player_id for key")
        self.player_id = str(player_id)
        return self.player_id

    def discover_match(self) -> str:
        """Finds the active match this player belongs to.

        Prefers non-finished matches; raises when the player belongs
        to multiple active matches unless match_id is set explicitly.
        """
        self.resolve_identity()
        payload = self._request("GET", "/v1/matches")
        candidates = [
            row
            for row in payload.get("matches", [])
            if isinstance(row, Mapping)
            and self.player_id in row.get("player_ids", ())
        ]
        active = [row for row in candidates if row.get("status") != "finished"]
        if active:
            candidates = active
        if len(candidates) == 1:
            match_id = candidates[0].get("match_id")
            self.match_id = str(match_id)
            return self.match_id
        if not candidates:
            raise RuntimeError(
                f"No match found containing player {self.player_id}"
            )
        ids = [str(row.get("match_id")) for row in candidates]
        raise RuntimeError(
            f"Player {self.player_id} belongs to multiple matches"
            f" ({', '.join(ids)}); set match_id explicitly."
        )

    def receive_game_state(
        self, data: Union[str, Mapping[str, Any]]
    ) -> GameState:
        """Converts incoming dict/JSON payload to structured GameState."""
        if isinstance(data, str):
            state = self.parser.parse_json(data, hero_index=self.player_index)
        else:
            state = self.parser.parse(data, hero_index=self.player_index)
        self.last_state = state
        return state

    def is_bot_turn(self, game_state: Optional[GameState] = None) -> bool:
        """Detects whether it is currently this bot's turn."""
        state = game_state or self.last_state
        if state is None:
            return False
        if self.player_index is not None:
            return state.is_bot_turn(self.player_index)
        return state.is_my_turn

    def get_action_history(self) -> Tuple[ActionRecord, ...]:
        """Returns action history from the latest parsed game state."""
        if self.last_state is None:
            return ()
        return self.last_state.action_history

    def fetch_state_snapshot(self) -> GameState:
        """Fetches the current viewer state without action history."""
        self.resolve_identity()
        query = urllib.parse.urlencode({"viewer_id": self.player_id})
        payload = self._request("GET", f"/v1/matches/{self.match_id}?{query}")
        self._maybe_discover_seat(payload.get("state", {}))
        self._validate_membership(payload.get("state", {}))
        return self.receive_game_state(payload)

    def fetch_action_history(self, history_limit: int = 200) -> list[dict]:
        """Fetches recent action events for the current match."""
        events_path = (
            f"/v1/matches/{self.match_id}/events"
            f"?offset=0&limit={max(1, history_limit)}"
        )
        events_payload = self._request("GET", events_path)
        return self._history_from_events(events_payload.get("events", []))

    def fetch_latest_state(self, history_limit: int = 200) -> GameState:
        """Fetches current state and recent history over HTTP."""
        self.resolve_identity()
        query = urllib.parse.urlencode({"viewer_id": self.player_id})
        state_payload = self._request(
            "GET", f"/v1/matches/{self.match_id}?{query}"
        )
        self._maybe_discover_seat(state_payload.get("state", {}))
        self._validate_membership(state_payload.get("state", {}))

        history = self.fetch_action_history(history_limit=history_limit)

        merged = {
            "match_id": state_payload.get("match_id", self.match_id),
            "state": state_payload.get("state", {}),
            "action_history": history,
        }
        return self.receive_game_state(merged)

    def maybe_act_on_current_state(self) -> Optional[Dict[str, Any]]:
        """Calls bot.act and sends action only when it is the bot's turn."""
        if self.last_state is None:
            raise RuntimeError(
                "No game state available."
                " Call receive_game_state/fetch_latest_state first."
            )

        if self.last_state.status not in (None, "running"):
            return None

        if not self.is_bot_turn(self.last_state):
            return None

        action = self.bot.act(self.last_state)
        if not isinstance(action, Action):
            raise TypeError("PokerBot.act must return an Action")

        return self.send_action(action, game_state=self.last_state)

    def send_action(
        self, action: Action, game_state: Optional[GameState] = None
    ) -> Dict[str, Any]:
        """Sends fold/call/raise action back to the running engine."""
        state = game_state or self.last_state
        if state is None:
            raise RuntimeError("GameState required to send action")

        engine_action, amount = translate_action(action, state)
        body: Dict[str, Any] = {"action": engine_action}
        if amount is not None:
            body["amount"] = amount
        if state.turn_id is not None and state.turn_id >= 1:
            body["turn_id"] = state.turn_id

        if not self.api_key:
            raise PlayerSDKAuthError(
                "An API key is required to submit actions;"
                " pass api_key to PokerEngineClient or connect(api_key=...)."
            )
        headers: Dict[str, str] = {"X-API-Key": self.api_key}
        route = f"/v1/matches/{self.match_id}/actions/self"
        return self._request("POST", route, payload=body, headers=headers)

    def run_once(self, history_limit: int = 200) -> Optional[Dict[str, Any]]:
        """One cycle: fetch state, detect turn, call bot, submit."""
        self.fetch_latest_state(history_limit=history_limit)
        return self.maybe_act_on_current_state()

    def run_forever(
        self,
        *,
        poll_interval_seconds: float = 0.5,
        history_limit: int = 200,
        max_iterations: Optional[int] = None,
    ) -> Optional[GameState]:
        """Polls state and submits actions until the match finishes.

        Returns the final game state when the match reaches a terminal
        status, or after ``max_iterations`` polls when set.
        """
        iterations = 0
        transient_failures = 0
        while True:
            try:
                state = self.fetch_latest_state(history_limit=history_limit)
                transient_failures = 0
            except PlayerSDKBadRequestError:
                # Stale turn race; the next poll resyncs.
                time.sleep(max(0.0, poll_interval_seconds))
                continue
            except PlayerSDKAuthError:
                raise
            except PlayerSDKError:
                transient_failures += 1
                if transient_failures >= _MAX_TRANSIENT_FAILURES:
                    raise
                time.sleep(max(0.0, poll_interval_seconds))
                continue

            if state.status in _TERMINAL_STATUSES:
                return state

            try:
                self.maybe_act_on_current_state()
            except PlayerSDKBadRequestError:
                # Illegal for the server's current turn; resync next poll.
                pass

            iterations += 1
            if max_iterations is not None and iterations >= max_iterations:
                return state
            time.sleep(max(0.0, poll_interval_seconds))

    def _maybe_discover_seat(self, state_payload: Mapping[str, Any]) -> None:
        if self.player_index is not None or self.player_id is None:
            return
        index = find_player_index(state_payload.get("players"), self.player_id)
        if index is not None:
            self.player_index = index

    def _validate_membership(self, state_payload: Mapping[str, Any]) -> None:
        """Raises when this player is not part of the match."""
        if self.player_id is None or self.player_index is not None:
            return
        players = state_payload.get("players")
        if not isinstance(players, list) or not players:
            return
        if state_payload.get("status") == "finished":
            return
        raise RuntimeError(
            f"Player {self.player_id} is not a player in match"
            f" {self.match_id}; check your api_key and match_id."
        )

    def _history_from_events(self, events: Any) -> list[dict]:
        """Builds action history rows from the flat match event log."""
        if not isinstance(events, list):
            return []

        history = []
        for row in events:
            if not isinstance(row, Mapping):
                continue
            if row.get("type") != "action":
                continue
            history.append(
                {
                    "player_id": row.get("player_id"),
                    "action": row.get("action"),
                    "amount": row.get("amount"),
                    "street": row.get("street"),
                    "timestamp": row.get("timestamp"),
                }
            )
        return history

    def _request(
        self,
        method: str,
        path: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        merged_headers = dict(headers or {})
        if self.api_key and "X-API-Key" not in merged_headers:
            merged_headers["X-API-Key"] = self.api_key
        return http_json(
            self.base_url,
            method,
            path,
            payload=payload,
            headers=merged_headers,
            timeout_seconds=self.timeout_seconds,
        )
