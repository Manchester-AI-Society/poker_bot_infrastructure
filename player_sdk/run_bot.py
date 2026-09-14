"""CLI entry point for running a bot against a live match.

Usage: python -m player_sdk.run_bot my_bot.py [--api-key KEY]
"""

from ._run import main

if __name__ == "__main__":
    main()
