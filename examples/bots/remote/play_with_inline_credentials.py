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
    """Plays a match with every credential passed inline.

    The OpenAI-SDK-style equivalent of:

        client = OpenAI()
        client.responses.create(model=..., input=...)

    Here the bot is the "model" and no client is instantiated at
    all — api_key, server_url, and match_id are mandatory and are
    passed straight through the call:

        play(MyBot(), api_key=..., server_url=..., match_id=...)
    """
    result = play(
        model=ExampleConservativeBot(),
        api_key="dev-key-1",
        server_url="http://127.0.0.1:8000",
        match_id=os.environ.get("POKER_MATCH_ID", "m_123"),
    )
    if result is not None:
        print(f"summary: {result.summary}")
        final_stacks = dict(zip(result.player_ids, result.stack_sizes))
        print(f"final stacks: {final_stacks}")


if __name__ == "__main__":
    main()
