from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from examples.bots.conservative_bot import ExampleConservativeBot
from player_sdk import play


def main() -> None:
    """Runs a bot against a live match with a single play() call.

    play() requires api_key, server_url, and match_id explicitly.
    This example reads them from the environment so the same script
    works for any player:

        POKER_API_KEY=dev-key-1 POKER_MATCH_ID=<match-id> \
            python examples/bots/remote/run_remote_bot.py

    Equivalent CLI (which resolves the same variables itself):

        POKER_API_KEY=dev-key-1 POKER_MATCH_ID=<match-id> \
            poker-bot examples/bots/conservative_bot.py
    """
    match_id = os.environ.get("POKER_MATCH_ID", "").strip()
    if not match_id:
        raise SystemExit(
            "Set POKER_MATCH_ID to the match you were assigned;"
            " play() requires match_id explicitly."
        )

    result = play(
        model=ExampleConservativeBot(),
        api_key=os.environ.get("POKER_API_KEY", "dev-key-1"),
        server_url=os.environ.get("POKER_SERVER_URL", "http://127.0.0.1:8000"),
        match_id=match_id,
    )
    if result is not None:
        print(result.summary)


if __name__ == "__main__":
    main()
