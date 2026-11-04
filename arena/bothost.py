"""Child process that hosts one participant bot.

Run as ``python -m arena.bothost <bot.py | bot_dir>``. Speaks JSON lines
on stdin/stdout:

    -> {"type": "act", "state": {...}, "hero_index": 0,
        "action_history": [...]}
    <- {"type": "action", "action": "raise_to", "amount": 60}
    <- {"type": "error", "message": "..."}      (bot raised; stays alive)

The first line the host writes is ``{"type": "ready"}`` once the bot
is imported, or a fatal ``error`` if loading failed. The bot's own
``print`` output is redirected to stderr (the team-private log) so it
cannot corrupt the protocol.
"""

from __future__ import annotations

import json
import os
import sys
import traceback
from pathlib import Path
from typing import Any, Dict, Mapping

from player_sdk._run import load_bot_from_file
from player_sdk.bot_interface import PokerBot
from player_sdk.client import translate_action
from player_sdk.models import Action
from player_sdk.parser import GameStateParser


def resolve_bot_file(target: Path) -> Path:
    """Returns the bot module for a file or a bot directory."""
    if target.is_dir():
        candidate = target / "bot.py"
        if not candidate.is_file():
            raise FileNotFoundError(f"{target} has no bot.py")
        return candidate
    if not target.is_file():
        raise FileNotFoundError(f"Bot not found: {target}")
    return target


def load_bot(target: Path) -> PokerBot:
    """Imports and instantiates the single PokerBot in ``target``."""
    bot_file = resolve_bot_file(target)
    bot_dir = str(bot_file.parent)
    if bot_dir not in sys.path:
        # Appended, not prepended: a team file named like a stdlib
        # module must not shadow the standard library.
        sys.path.append(bot_dir)
    os.chdir(bot_dir)
    return load_bot_from_file(bot_file)


def act_on_message(
    bot: PokerBot, parser: GameStateParser, message: Mapping[str, Any]
) -> Dict[str, Any]:
    """Runs the bot on one ``act`` message; shared with in-process use."""
    state_payload = dict(message["state"])
    state_payload["action_history"] = message.get("action_history", [])
    game_state = parser.parse(
        {"state": state_payload}, hero_index=int(message["hero_index"])
    )
    action = bot.act(game_state)
    if not isinstance(action, Action):
        raise TypeError(
            f"PokerBot.act must return an Action, got {type(action).__name__}"
        )
    engine_action, amount = translate_action(action, game_state)
    return {"type": "action", "action": engine_action, "amount": amount}


def _send(stream, payload: Mapping[str, Any]) -> None:
    stream.write(json.dumps(payload, separators=(",", ":")) + "\n")
    stream.flush()


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("usage: python -m arena.bothost <bot.py | bot_dir>")
        return 2

    protocol_out = sys.stdout
    sys.stdout = sys.stderr  # bot prints go to the private log

    try:
        bot = load_bot(Path(args[0]).resolve())
    except Exception:
        _send(
            protocol_out,
            {
                "type": "error",
                "fatal": True,
                "message": traceback.format_exc(limit=8),
            },
        )
        return 1

    _send(protocol_out, {"type": "ready"})
    parser = GameStateParser()
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
            if message.get("type") == "quit":
                return 0
            reply = act_on_message(bot, parser, message)
        except Exception:
            reply = {
                "type": "error",
                "message": traceback.format_exc(limit=6),
            }
        _send(protocol_out, reply)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
