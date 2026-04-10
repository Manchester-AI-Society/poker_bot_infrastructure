from __future__ import annotations

from typing import Dict, List, Optional

from server.game.game_domain_models import MatchState


class InMemoryMatchRepository:
    """Simple in-memory match repository for local single-process runtime."""

    def __init__(self) -> None:
        """Initialises the in-memory match repository.

        Args:
            None: This function does not take external arguments.

        Returns:
            None: This function does not return a value.
        """
        self._matches: Dict[str, MatchState] = {}

    def save(self, match: MatchState) -> None:
        """Inserts or updates a match state.

        Args:
            match (MatchState): Match state to persist in memory.

        Returns:
            None: This function does not return a value.
        """
        self._matches[match.match_id] = match

    def get(self, match_id: str) -> Optional[MatchState]:
        """Gets a match by identifier when present.

        Args:
            match_id (str): Match identifier.

        Returns:
            Optional[MatchState]: Stored match state when available.
        """
        return self._matches.get(match_id)

    def list_all(self) -> List[MatchState]:
        """Lists all matches currently held in memory.

        Args:
            None: This function does not take external arguments.

        Returns:
            List[MatchState]: Collection of currently stored match states.
        """
        return list(self._matches.values())
