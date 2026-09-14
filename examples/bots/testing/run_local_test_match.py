import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from examples.bots.conservative_bot import ExampleConservativeBot
from player_sdk.testing import play_local_match


def main() -> None:
    """Runs a local test match between two bots and announces the winner.

    Use this to test your bot end-to-end before connecting it to a real
    game: a local server is auto-started and the match runs to completion.
    """
    print("[example] Creating mock match...")
    result = play_local_match(
        [ExampleConservativeBot(), ExampleConservativeBot()],
        turn_timeout_seconds=8,
        max_duration_seconds=120,
    )

    print("[example] Winner announced.")
    print(
        {
            "match_id": result.match_id,
            "winner": result.winner_id,
            "winning_stack": result.winning_stack,
            "final_status": result.status,
        }
    )


if __name__ == "__main__":
    main()
