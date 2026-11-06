"""Two-round knockout tournament built on top of GameService matches.

Round 1 splits the entrants across up to ``MAX_TABLES`` parallel tables;
each table plays until one player owns every chip (or the hand cap hits,
in which case the chip leader advances). Round 2 is a single final table
of the round-1 winners, whose winner is the champion.
"""

from __future__ import annotations

import asyncio
import random
from typing import Any, Awaitable, Callable, Dict, List, Optional

from .game_domain_models import MatchStateError
from .game_service_core import GameService
from .match_runtime import MatchRuntime

MAX_TABLES = 10
SendCallback = Callable[[str, Dict[str, Any]], Awaitable[None]]


def split_into_tables(player_ids: List[str]) -> List[List[str]]:
    """Deals players round-robin onto ``min(10, n // 2)`` tables.

    Table sizes differ by at most one and every table has >= 2 seats.
    """
    if len(player_ids) < 2:
        raise MatchStateError("At least 2 players are required")
    table_count = min(MAX_TABLES, len(player_ids) // 2)
    return [player_ids[i::table_count] for i in range(table_count)]


def table_winner(runtime: MatchRuntime) -> str:
    """Player advancing from a finished table.

    Natural ends already set ``winner_ids``; admin-ended tables fall
    back to the chip leader.
    """
    # ponytail: ties go to the first listed seat; coin-flip if it matters.
    if runtime.winner_ids:
        return runtime.winner_ids[0]
    return max(runtime.players, key=lambda seat: seat.curr_balance).player_id


class Tournament:
    """In-memory orchestrator for one two-round tournament.

    # ponytail: one tournament per server process, in memory; persist
    # state if surviving restarts ever matters.
    """

    def __init__(
        self, games: GameService, send_cb: Optional[SendCallback] = None
    ) -> None:
        self._games = games
        self._send = send_cb
        self._lock = asyncio.Lock()
        self._settings: Dict[str, Any] = {}
        self.status = "idle"
        self.round = 0
        self.entrants: List[str] = []
        self.tables: List[Dict[str, Any]] = []
        self.history: List[List[Dict[str, Any]]] = []
        self.champion: Optional[str] = None

    async def start(self, player_ids: List[str], **settings: Any) -> None:
        """Seats the entrants and launches round 1 (or the final)."""
        async with self._lock:
            if self.status == "running":
                raise MatchStateError("A tournament is already running")
            entrants = list(dict.fromkeys(player_ids))
            groups = split_into_tables(random.sample(entrants, len(entrants)))
            self._settings = settings
            self.entrants = entrants
            self.history = []
            self.tables = []
            self.champion = None
            self.status = "running"
            # A lone table is already the final.
            launched = self._create_round(1 if len(groups) > 1 else 2, groups)
        await self._start_tables(launched)

    async def on_match_ended(self, runtime: MatchRuntime) -> None:
        """Records a table result and advances the bracket when complete."""
        launched: List[MatchRuntime] = []
        notices: List[tuple[str, Dict[str, Any]]] = []
        async with self._lock:
            table = next(
                (t for t in self.tables if t["match_id"] == runtime.match_id),
                None,
            )
            if table is None or table["winner"] is not None:
                return
            winner = table_winner(runtime)
            table["winner"] = winner
            notices = [
                (
                    player_id,
                    {
                        "type": "eliminated",
                        "round": self.round,
                        "match_id": runtime.match_id,
                        "winner": winner,
                    },
                )
                for player_id in table["player_ids"]
                if player_id != winner
            ]

            if all(t["winner"] is not None for t in self.tables):
                winners = [t["winner"] for t in self.tables]
                if self.round == 1:
                    launched = self._create_round(2, [winners])
                else:
                    self.champion = winners[0]
                    self.status = "finished"
                    event = {"type": "tournament_ended", **self.snapshot()}
                    notices += [(p, event) for p in self.entrants]

        for player_id, event in notices:
            await self._notify(player_id, event)
        await self._start_tables(launched)

    def snapshot(self) -> Dict[str, Any]:
        """Public view of the bracket."""
        return {
            "status": self.status,
            "round": self.round,
            "entrants": list(self.entrants),
            "tables": [dict(t) for t in self.tables],
            "completed_rounds": [
                [dict(t) for t in tables] for tables in self.history
            ],
            "champion": self.champion,
        }

    def _create_round(
        self, round_number: int, groups: List[List[str]]
    ) -> List[MatchRuntime]:
        """Creates (but does not start) one match per table group."""
        if self.tables:
            self.history.append(self.tables)
        self.round = round_number
        self.tables = []
        runtimes = []
        for group in groups:
            runtime = self._games.create_match(
                player_ids=group,
                starting_stack=self._settings.get("starting_stack", 1000),
                small_blind=self._settings.get("small_blind", 10),
                big_blind=self._settings.get("big_blind", 20),
                turn_timeout_seconds=self._settings.get(
                    "turn_timeout_seconds", 15
                ),
                max_hands=self._settings.get("max_hands"),
                blind_increase_every_hands=self._settings.get(
                    "blind_increase_every_hands"
                ),
            )
            self.tables.append(
                {
                    "match_id": runtime.match_id,
                    "player_ids": list(group),
                    "winner": None,
                }
            )
            runtimes.append(runtime)
        return runtimes

    async def _start_tables(self, runtimes: List[MatchRuntime]) -> None:
        """Tells each player their table, then deals.

        Runs outside the bracket lock: a table can finish during its own
        opening deal, which re-enters ``on_match_ended``. Entrants come
        from live connections, so tables are force-started; a bot that
        drops is auto-checked/folded rather than stalling its table.
        """
        for runtime in runtimes:
            player_ids = [seat.player_id for seat in runtime.players]
            for player_id in player_ids:
                await self._notify(
                    player_id,
                    {
                        "type": "table_assigned",
                        "round": self.round,
                        "match_id": runtime.match_id,
                        "player_ids": player_ids,
                    },
                )
        for runtime in runtimes:
            await self._games.start_match(runtime.match_id, force=True)

    async def _notify(self, player_id: str, event: Dict[str, Any]) -> None:
        if self._send is not None:
            await self._send(player_id, event)
