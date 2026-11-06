"""Connect your bot to the arena: ``python -m arena.connect``.

Your bot runs on YOUR machine (so any model, GPU or API key stays with you);
this program only carries its moves to the arena over a websocket.

First time (the organiser announces the address and a join code):

    python -m arena.connect --url ws://HOST:8765 --team fox --code CODE bots/x

That registers your team and saves your secret key on this computer. After
that you only need:

    python -m arena.connect --url ws://HOST:8765 --team fox bots/mybot

``bots/mybot`` is a folder with ``bot.py`` (or a single ``.py`` file), exactly
as for ``python -m arena match``. Your key is the secret that proves you are
that team: keep it to yourselves. (You can also give it explicitly with
``--key``, or the ARENA_KEY environment variable.)

Leave it running for the whole event. If the connection drops it reconnects
by itself; the arena asks for each move with a time limit (the organiser says
what it is, 1 second by default), and that time includes the network.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Union

from player_sdk.bot_interface import PokerBot
from player_sdk.parser import GameStateParser

from .bothost import act_on_message, load_bot
from .gateway import PROTOCOL

EXIT_REJECTED = 3
RECONNECT_FIRST_SECONDS = 1.0
RECONNECT_MAX_SECONDS = 15.0
# A connection attempt that stalls is abandoned and tried again.
CONNECT_TIMEOUT_SECONDS = 5.0


class Rejected(Exception):
    """The arena refused this connection (wrong key, old client)."""


@dataclass
class Credentials:
    """How to log in: a key, or a team name and join code to get one."""

    key: Optional[str] = None
    team: Optional[str] = None
    code: Optional[str] = None
    # Called with (team, key) once a registration succeeds.
    on_key: Optional[Callable[[str, str], None]] = None


def key_file(team: str) -> Path:
    """Where this computer keeps a team's key (ARENA_HOME overrides)."""
    home = os.environ.get("ARENA_HOME")
    base = Path(home) if home else Path.home() / ".arena"
    return base / "keys" / f"{team}.key"


def save_key(team: str, key: str) -> Path:
    path = key_file(team)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(key + "\n", encoding="utf-8")
    try:
        path.chmod(0o600)  # owner only, where the system supports it
    except OSError:
        pass
    return path


def load_key(team: str) -> Optional[str]:
    try:
        value = key_file(team).read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return value or None


def _log(message: str) -> None:
    print(f"[arena {time.strftime('%H:%M:%S')}] {message}", flush=True)


def _reply_to(
    bot: PokerBot, parser: GameStateParser, message: Dict[str, Any]
) -> Dict[str, Any]:
    """The reply to one ``act`` message; a bot error becomes an error reply."""
    try:
        reply = act_on_message(bot, parser, message)
    except Exception:
        reply = {
            "type": "error",
            "message": traceback.format_exc(limit=6),
        }
        _log("your bot raised an error (sent to the arena as a fault):")
        print(reply["message"], file=sys.stderr, flush=True)
    reply["id"] = message.get("id")
    return reply


def _call_hook(bot: PokerBot, name: str, log: Callable[[str], None]) -> None:
    """Calls an optional method of the team's bot; its errors stay local."""
    hook = getattr(bot, name, None)
    if not callable(hook):
        return
    try:
        hook()
    except Exception:
        log(f"your bot's {name}() raised an error (ignored):")
        print(traceback.format_exc(limit=6), file=sys.stderr, flush=True)


def serve_connection(
    ws,
    bot: PokerBot,
    credentials: Union[str, Credentials],
    log: Callable[[str], None] = _log,
) -> None:
    """Plays on one open connection until it closes."""
    if isinstance(credentials, str):
        credentials = Credentials(key=credentials)
    if credentials.key:
        ws.send(
            json.dumps(
                {"type": "hello", "key": credentials.key, "protocol": PROTOCOL}
            )
        )
    else:
        ws.send(
            json.dumps(
                {
                    "type": "register",
                    "team": credentials.team,
                    "code": credentials.code,
                    "protocol": PROTOCOL,
                }
            )
        )
    first = json.loads(ws.recv(timeout=15))
    if first.get("type") == "rejected":
        raise Rejected(str(first.get("message", "rejected")))
    if first.get("type") == "registered":
        # Keep the key: from now on this computer logs in with it.
        credentials.key = first["key"]
        credentials.team = first["team"]
        if credentials.on_key is not None:
            credentials.on_key(first["team"], first["key"])
        log(f"registered team {first['team']!r}")
    elif first.get("type") != "welcome":
        raise Rejected(f"unexpected reply from the arena: {first!r}")
    log(f"connected as team {first.get('team')!r}; waiting for matches")

    parser = GameStateParser()
    for raw in ws:
        if not isinstance(raw, str):
            continue
        try:
            message = json.loads(raw)
        except ValueError:
            continue
        kind = message.get("type") if isinstance(message, dict) else None
        if kind == "act":
            ws.send(
                json.dumps(
                    _reply_to(bot, parser, message), separators=(",", ":")
                )
            )
        elif kind == "match_start":
            parser = GameStateParser()  # a new opponent: start clean
            log(f"match starting ({message.get('deals', '?')} deals)")
            _call_hook(bot, "on_match_start", log)
        elif kind == "match_end":
            log("match finished")


def run(
    bot: PokerBot,
    url: str,
    credentials: Union[str, Credentials],
    *,
    log: Callable[[str], None] = _log,
    stop: Optional[Callable[[], bool]] = None,
) -> int:
    """Stays connected, reconnecting after any drop. Returns an exit code."""
    from websockets.exceptions import (
        ConnectionClosed,
        InvalidHandshake,
        InvalidURI,
    )
    from websockets.sync.client import connect

    if isinstance(credentials, str):
        credentials = Credentials(key=credentials)
    delay = RECONNECT_FIRST_SECONDS
    while stop is None or not stop():
        try:
            with connect(
                url, max_size=64 * 1024, open_timeout=CONNECT_TIMEOUT_SECONDS
            ) as ws:
                delay = RECONNECT_FIRST_SECONDS
                serve_connection(ws, bot, credentials, log)
        except Rejected as exc:
            log(f"the arena refused the connection: {exc}")
            return EXIT_REJECTED
        except InvalidURI as exc:
            log(f"that address is not a websocket URL: {exc}")
            return 2
        except (
            ConnectionClosed,
            InvalidHandshake,
            OSError,
            TimeoutError,
            EOFError,
            ValueError,
        ) as exc:
            log(f"connection lost ({type(exc).__name__}); retrying")
        except KeyboardInterrupt:
            log("stopped")
            return 0
        if stop is not None and stop():
            break
        time.sleep(delay)
        delay = min(delay * 2, RECONNECT_MAX_SECONDS)
    return 0


def resolve_credentials(
    key: Optional[str], team: Optional[str], code: Optional[str]
) -> Optional[Credentials]:
    """Chooses how to log in, or None if there is not enough to go on.

    An explicit key wins, then a key saved for the team on this computer
    (so running the registration command twice is harmless), and only then a
    registration with the join code.
    """

    def remember(name: str, value: str) -> None:
        path = save_key(name, value)
        _log(f"your team key is saved in {path}")
        _log("keep that file private; if you lose it, ask the organiser")

    if key:
        return Credentials(key=key, team=team)
    if team:
        saved = load_key(team)
        if saved:
            return Credentials(key=saved, team=team)
        if code:
            return Credentials(team=team, code=code, on_key=remember)
    return None


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m arena.connect",
        description="Play your bot in the arena over a websocket.",
    )
    parser.add_argument("bot", help="bot folder (with bot.py) or .py file")
    parser.add_argument("--url", required=True, help="ws://HOST:PORT")
    parser.add_argument("--team", help="your team name")
    parser.add_argument(
        "--code",
        default=os.environ.get("ARENA_CODE"),
        help="the join code the organiser announced (first time only)",
    )
    parser.add_argument(
        "--key", default=os.environ.get("ARENA_KEY"), help="your team's key"
    )
    args = parser.parse_args(argv)
    credentials = resolve_credentials(args.key, args.team, args.code)
    if credentials is None:
        print(
            "to register: --team NAME --code JOINCODE (the organiser gives "
            "you the code); to play with a key you already have: "
            "--team NAME, or --key KEY"
        )
        return 2
    try:
        bot = load_bot(Path(args.bot).resolve())
    except Exception:
        print("your bot could not be loaded:")
        print(traceback.format_exc(limit=8))
        return 1
    _log(f"bot loaded; connecting to {args.url}")
    try:
        return run(bot, args.url, credentials)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
