from dataclasses import dataclass
from typing import List, Optional


@dataclass
class MatchCreationOptions:
    """Defines options for creating a match through the admin SDK."""

    player_ids: List[str]
    number_of_bots_allowed: int
    starting_stack: int = 1000
    small_blind: int = 10
    big_blind: int = 20
    turn_timeout_seconds: int = 15
    event_log_limit: int = 2000
    max_hands: Optional[int] = None
    wait_for_players: bool = True


@dataclass
class EndMatchOptions:
    """Defines options for ending a match through the admin SDK."""

    reason: Optional[str] = None
    mode: str = "terminate_as_is"
