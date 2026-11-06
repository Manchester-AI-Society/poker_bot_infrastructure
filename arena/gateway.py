"""The websocket gateway: teams' bots connect here and play from their own
machines, so the organiser never runs (or pays for) a team's bot.

Protocol (JSON text frames, one object each):

    team   -> {"type": "hello", "key": "...", "protocol": 1}
    server -> {"type": "welcome", "team": "fox"}
              or {"type": "rejected", "message": "..."} then the socket closes

    server -> {"type": "match_start", "match": "...", "deals": 100}
    server -> {"type": "act", "id": 7, "state": {...}, "hero_index": 0,
               "action_history": [...]}
              (the same message ``arena.bothost`` is given)
    team   -> {"type": "action", "id": 7, "action": "raise_to", "amount": 60}
              or {"type": "error", "id": 7, "message": "..."}
    server -> {"type": "match_end", "match": "..."}

A reply counts only if it carries the id of the request it answers, so a
late reply to an earlier move can never be mistaken for the current one.

The gateway runs its own event loop on a background thread; matches are played
by ordinary threads through :class:`RemoteAgent`, which is the same ``Agent``
interface a child-process bot uses, so scoring, the fault guard and the time
limits are exactly the ones every other bot gets.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import threading
import time
from concurrent.futures import TimeoutError as FutureTimeout
from typing import Any, Dict, List, Mapping, Optional, Set

from websockets.asyncio.server import serve
from websockets.exceptions import ConnectionClosed

from .agents import Agent, AgentCrashed, AgentFault, AgentTimeout
from .store import Store

PROTOCOL = 1
# Biggest frame accepted from a team (a reply is a few dozen bytes).
MAX_MESSAGE_BYTES = 64 * 1024
HELLO_TIMEOUT_SECONDS = 10.0
# Close codes: 4400 protocol, 4401 bad key, 4409 replaced by a newer one.
CLOSE_PROTOCOL = 4400
CLOSE_BAD_KEY = 4401
CLOSE_REPLACED = 4409


def hash_key(key: str) -> str:
    """What the store keeps instead of a team's secret key."""
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


class _Link:
    """One live connection from a team."""

    def __init__(self, team: str, ws) -> None:
        self.team = team
        self.ws = ws
        self.replies: "asyncio.Queue[Dict[str, Any]]" = asyncio.Queue()
        self.next_id = 0
        self.connected_at = time.time()


class Gateway:
    """Accepts team connections and lets match threads talk to them."""

    def __init__(
        self,
        store: Store,
        host: str = "127.0.0.1",
        port: int = 8765,
        *,
        ping_interval: float = 15.0,
    ) -> None:
        self.store = store
        self.host = host
        self.port = port
        self._ping_interval = ping_interval
        self._links: Dict[str, _Link] = {}
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._ready = threading.Event()
        self._stop: Optional[asyncio.Event] = None
        self._error: Optional[BaseException] = None

    # -- lifecycle -------------------------------------------------------

    def start(self) -> "Gateway":
        """Starts listening; returns once the port is open (or raises)."""
        self._thread = threading.Thread(
            target=self._run, name="arena-gateway", daemon=True
        )
        self._thread.start()
        if not self._ready.wait(timeout=15):
            raise RuntimeError("the gateway did not start")
        if self._error is not None:
            raise RuntimeError(
                f"cannot listen on {self.host}:{self.port}: {self._error}"
            ) from self._error
        return self

    def stop(self) -> None:
        loop, stop = self._loop, self._stop
        if loop is not None and stop is not None and not loop.is_closed():
            loop.call_soon_threadsafe(stop.set)
        if self._thread is not None:
            self._thread.join(timeout=10)

    def _run(self) -> None:
        loop = asyncio.new_event_loop()
        self._loop = loop
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._serve())
        except BaseException as exc:  # reported to start()
            self._error = exc
            self._ready.set()
        finally:
            loop.close()

    async def _serve(self) -> None:
        self._stop = asyncio.Event()
        async with serve(
            self._handle,
            self.host,
            self.port,
            max_size=MAX_MESSAGE_BYTES,
            ping_interval=self._ping_interval,
            ping_timeout=self._ping_interval,
        ) as server:
            sockets = server.sockets or []
            if sockets:
                self.port = sockets[0].getsockname()[1]
            self._ready.set()
            await self._stop.wait()

    # -- who is connected -------------------------------------------------

    def connected_teams(self) -> Set[str]:
        return set(self._links)

    def is_connected(self, team: str) -> bool:
        return team in self._links

    # -- one connection ---------------------------------------------------

    def _team_for_key(self, key: Any) -> Optional[str]:
        if not isinstance(key, str) or not key or len(key) > 200:
            return None
        wanted = hash_key(key)
        for team, stored in self.store.remote_teams().items():
            if stored == wanted:
                return team
        return None

    async def _handle(self, ws) -> None:
        link: Optional[_Link] = None
        try:
            try:
                raw = await asyncio.wait_for(ws.recv(), HELLO_TIMEOUT_SECONDS)
                hello = json.loads(raw)
            except (asyncio.TimeoutError, ValueError, TypeError):
                await ws.close(CLOSE_PROTOCOL, "expected a hello message")
                return
            if not isinstance(hello, dict) or hello.get("type") != "hello":
                await ws.close(CLOSE_PROTOCOL, "expected a hello message")
                return
            if hello.get("protocol") != PROTOCOL:
                await self._reject(
                    ws,
                    CLOSE_PROTOCOL,
                    f"this arena speaks protocol {PROTOCOL}; update "
                    "arena.connect",
                )
                return
            team = self._team_for_key(hello.get("key"))
            if team is None:
                await self._reject(ws, CLOSE_BAD_KEY, "that key is not valid")
                return

            link = _Link(team, ws)
            previous = self._links.get(team)
            self._links[team] = link
            if previous is not None:
                # The same team reconnecting (a dropped Wi-Fi, a restart):
                # the newest connection wins.
                try:
                    await previous.ws.close(CLOSE_REPLACED, "replaced")
                except ConnectionClosed:
                    pass
            self.store.set_presence(team, True)
            await ws.send(json.dumps({"type": "welcome", "team": team}))

            async for raw in ws:
                if not isinstance(raw, str):
                    continue  # binary frames are not part of the protocol
                try:
                    message = json.loads(raw)
                except ValueError:
                    continue
                if isinstance(message, dict) and message.get("type") in (
                    "action",
                    "error",
                ):
                    link.replies.put_nowait(message)
        except ConnectionClosed:
            pass
        finally:
            if link is not None and self._links.get(link.team) is link:
                del self._links[link.team]
                self.store.set_presence(link.team, False)

    @staticmethod
    async def _reject(ws, code: int, message: str) -> None:
        try:
            await ws.send(json.dumps({"type": "rejected", "message": message}))
        except ConnectionClosed:
            return
        await ws.close(code, message[:100])

    # -- talking to a team from a match thread ------------------------------

    def notify(self, team: str, message: Mapping[str, Any]) -> bool:
        """Sends a message that needs no reply; False if it could not."""
        link = self._links.get(team)
        loop = self._loop
        if link is None or loop is None or loop.is_closed():
            return False
        future = asyncio.run_coroutine_threadsafe(
            self._send(link, dict(message)), loop
        )
        try:
            future.result(timeout=5)
        except Exception:
            return False
        return True

    @staticmethod
    async def _send(link: _Link, message: Dict[str, Any]) -> None:
        await link.ws.send(json.dumps(message, separators=(",", ":")))

    def exchange(
        self, team: str, message: Mapping[str, Any], timeout: float
    ) -> Dict[str, Any]:
        """Sends a request and waits for its reply (match thread, blocking).

        Raises an AgentFault subclass for everything that can go wrong, so the
        caller's fault guard turns it into a fallback action.
        """
        link = self._links.get(team)
        loop = self._loop
        if link is None or loop is None or loop.is_closed():
            raise AgentCrashed("the bot is not connected")
        future = asyncio.run_coroutine_threadsafe(
            self._exchange(link, dict(message), timeout), loop
        )
        try:
            reply = future.result(timeout=timeout + 2.0)
        except (FutureTimeout, asyncio.TimeoutError):
            future.cancel()
            raise AgentTimeout(f"no reply within {timeout:.2f}s") from None
        except ConnectionClosed:
            raise AgentCrashed("the bot disconnected") from None
        if reply.get("type") == "error":
            raise AgentFault(str(reply.get("message", "bot error"))[-600:])
        return reply

    @staticmethod
    async def _exchange(
        link: _Link, message: Dict[str, Any], timeout: float
    ) -> Dict[str, Any]:
        link.next_id += 1
        request_id = link.next_id
        while not link.replies.empty():  # anything left over is stale
            link.replies.get_nowait()
        message["id"] = request_id
        await link.ws.send(json.dumps(message, separators=(",", ":")))
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                raise asyncio.TimeoutError
            reply = await asyncio.wait_for(link.replies.get(), remaining)
            if reply.get("id") == request_id:
                return reply
            # a late answer to an earlier move: ignore it

    def agent(self, team: str) -> "RemoteAgent":
        return RemoteAgent(self, team)


class RemoteAgent(Agent):
    """A team's connected bot, as the match engine's ``Agent``."""

    def __init__(self, gateway: Gateway, team: str) -> None:
        self._gateway = gateway
        self._team = team

    def request(self, message: Mapping[str, Any], timeout: float):
        return self._gateway.exchange(self._team, message, timeout)


def team_summary(gateway: Gateway) -> List[str]:
    """Connected teams, sorted (for status output)."""
    return sorted(gateway.connected_teams())
