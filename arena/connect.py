"""Connect your bot to the arena: ``python -m arena.connect``.

Your bot runs on YOUR machine (so any model, GPU or API key stays with you);
this program only carries its moves to the arena over a websocket.

    python -m arena.connect --url ws://HOST:8765 --key YOUR_KEY bots/mybot

``bots/mybot`` is a folder with ``bot.py`` (or a single ``.py`` file), exactly
as for ``python -m arena match``. The key is the secret the organiser gave
your team; keep it to yourselves (or set the ARENA_KEY environment variable
instead of putting it on the command line).

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
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from player_sdk.bot_interface import PokerBot
from player_sdk.parser import GameStateParser

from .bothost import act_on_message, load_bot
from .gateway import PROTOCOL

EXIT_REJECTED = 3
RECONNECT_FIRST_SECONDS = 1.0
RECONNECT_MAX_SECONDS = 15.0


class Rejected(Exception):
    """The arena refused this connection (wrong key, old client)."""


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


def serve_connection(
    ws, bot: PokerBot, key: str, log: Callable[[str], None] = _log
) -> None:
    """Plays on one open connection until it closes."""
    ws.send(json.dumps({"type": "hello", "key": key, "protocol": PROTOCOL}))
    first = json.loads(ws.recv(timeout=15))
    if first.get("type") == "rejected":
        raise Rejected(str(first.get("message", "rejected")))
    if first.get("type") != "welcome":
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
        elif kind == "match_end":
            log("match finished")


def run(
    bot: PokerBot,
    url: str,
    key: str,
    *,
    log: Callable[[str], None] = _log,
    stop: Optional[Callable[[], bool]] = None,
) -> int:
    """Stays connected, reconnecting after any drop. Returns an exit code."""
    from websockets.exceptions import ConnectionClosed, InvalidURI
    from websockets.sync.client import connect

    delay = RECONNECT_FIRST_SECONDS
    while stop is None or not stop():
        try:
            with connect(url, max_size=64 * 1024, open_timeout=10) as ws:
                delay = RECONNECT_FIRST_SECONDS
                serve_connection(ws, bot, key, log)
        except Rejected as exc:
            log(f"the arena refused the connection: {exc}")
            return EXIT_REJECTED
        except InvalidURI as exc:
            log(f"that address is not a websocket URL: {exc}")
            return 2
        except (ConnectionClosed, OSError, TimeoutError) as exc:
            log(f"connection lost ({type(exc).__name__}); retrying")
        except KeyboardInterrupt:
            log("stopped")
            return 0
        if stop is not None and stop():
            break
        time.sleep(delay)
        delay = min(delay * 2, RECONNECT_MAX_SECONDS)
    return 0


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m arena.connect",
        description="Play your bot in the arena over a websocket.",
    )
    parser.add_argument("bot", help="bot folder (with bot.py) or .py file")
    parser.add_argument("--url", required=True, help="ws://HOST:PORT")
    parser.add_argument(
        "--key", default=os.environ.get("ARENA_KEY"), help="your team's key"
    )
    args = parser.parse_args(argv)
    if not args.key:
        print("give your team's key with --key (or set ARENA_KEY)")
        return 2
    try:
        bot = load_bot(Path(args.bot).resolve())
    except Exception:
        print("your bot could not be loaded:")
        print(traceback.format_exc(limit=8))
        return 1
    _log(f"bot loaded; connecting to {args.url}")
    try:
        return run(bot, args.url, args.key)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
