"""Local testing utilities for poker bots.

These helpers auto-start a local server and drive a full match so you can
test bots before connecting them to a remote game. They are not intended
for production play; use :func:`player_sdk.play` (or the ``poker-bot``
CLI) to join a real game.
"""

from .local_server import ensure_server_running
from .match_runner import MatchResult, act_for_player, play_local_match

__all__ = [
    "MatchResult",
    "act_for_player",
    "ensure_server_running",
    "play_local_match",
]
