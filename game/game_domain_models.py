from __future__ import annotations

import asyncio
import time
from collections import deque
from typing import (
    Any,
    Awaitable,
    Callable,
    Deque,
    Dict,
    Iterable,
    List,
    Optional,
)

from .player import Player


class MatchNotFoundError(KeyError):
    pass


class MatchStateError(RuntimeError):
    pass


class InvalidActionError(ValueError):
    pass


BroadcastCallback = Callable[[Iterable[str], Dict[str, Any]], Awaitable[None]]
DirectCallback = Callable[[str, Dict[str, Any]], Awaitable[None]]


class PlayerSeat:
    """Seat state for a single participant in the active match."""

    def __init__(
        self,
        player_id: str,
        stack: int,
        hole_cards: Optional[List[str]] = None,
        committed: int = 0,
        folded: bool = False,
        all_in: bool = False,
        acted: bool = False,
        actor: Optional[Player] = None,
    ) -> None:
        """Initialises per-seat state for a player in a match."""
        self.player_id = player_id
        self.stack = stack
        self.hole_cards = list(hole_cards) if hole_cards is not None else []
        self.committed = committed
        self.folded = folded
        self.all_in = all_in
        self.acted = acted
        self.actor = actor


class MatchState:
    """Mutable in-memory state for one poker match."""

    def __init__(
        self,
        match_id: str,
        players: List[PlayerSeat],
        small_blind: int,
        big_blind: int,
        turn_timeout_seconds: int,
        status: str = "waiting",
        street: str = "preflop",
        dealer_index: int = 0,
        acting_index: Optional[int] = None,
        current_bet: int = 0,
        min_raise_size: int = 0,
        pot: int = 0,
        board: Optional[List[str]] = None,
        deck: Optional[List[str]] = None,
        turn_id: int = 0,
        event_log_limit: int = 2000,
        action_log: Optional[Deque[Dict[str, Any]]] = None,
        lock: Optional[asyncio.Lock] = None,
        turn_task: Optional[asyncio.Task[Any]] = None,
        created_at: Optional[float] = None,
        paused_at: Optional[float] = None,
        paused_by: Optional[str] = None,
        pause_reason: Optional[str] = None,
        resumed_at: Optional[float] = None,
        admin_actions: Optional[List[Dict[str, Any]]] = None,
        winner_ids: Optional[List[str]] = None,
        end_reason: Optional[str] = None,
        updated_at: Optional[float] = None,
    ) -> None:
        """Initialises mutable match state and runtime metadata."""
        self.match_id = match_id
        self.players = players
        self.small_blind = small_blind
        self.big_blind = big_blind
        self.turn_timeout_seconds = turn_timeout_seconds
        self.status = status
        self.street = street
        self.dealer_index = dealer_index
        self.acting_index = acting_index
        self.current_bet = current_bet
        self.min_raise_size = min_raise_size
        self.pot = pot
        self.board = list(board) if board is not None else []
        self.deck = list(deck) if deck is not None else []
        self.turn_id = turn_id
        self.event_log_limit = event_log_limit
        self.action_log = action_log if action_log is not None else deque()
        self.lock = lock if lock is not None else asyncio.Lock()
        self.turn_task = turn_task
        self.created_at = created_at if created_at is not None else time.time()
        self.paused_at = paused_at
        self.paused_by = paused_by
        self.pause_reason = pause_reason
        self.resumed_at = resumed_at
        self.admin_actions = (
            list(admin_actions) if admin_actions is not None else []
        )
        self.winner_ids = list(winner_ids) if winner_ids is not None else []
        self.end_reason = end_reason
        self.updated_at = updated_at if updated_at is not None else time.time()

        if self.min_raise_size <= 0:
            self.min_raise_size = self.big_blind

    @property
    def current_player_index(self) -> Optional[int]:
        """Returns the index of the current acting player."""
        return self.acting_index

    @property
    def current_player_id(self) -> Optional[str]:
        """Returns the player id for the current acting seat."""
        if self.acting_index is None:
            return None
        if self.acting_index < 0:
            return None
        if self.acting_index >= len(self.players):
            return None
        return self.players[self.acting_index].player_id

    def state_for_player(self, viewer_id: Optional[str]) -> Dict[str, Any]:
        """Build a serialisable match state for a specific viewer.

        Args:
            viewer_id (Optional[str]): Player identifier requesting state.

        Returns:
            Dict[str, Any]: State payload for API responses.
        """
        players_state = []
        for seat in self.players:
            entry: Dict[str, Any] = {
                "id": seat.player_id,
                "stack": seat.stack,
                "bet": seat.committed,
                "folded": seat.folded,
                "all_in": seat.all_in,
            }
            if viewer_id is not None and viewer_id == seat.player_id:
                entry["hole_cards"] = list(seat.hole_cards)
            players_state.append(entry)

        current_player_id = None
        if self.acting_index is not None:
            current_player_id = self.players[self.acting_index].player_id

        state = {
            "players": players_state,
            "pot": self.pot,
            "board": list(self.board),
            "street": self.street,
            "status": self.status,
            "current_player_id": current_player_id,
            "turn_id": self.turn_id,
        }

        if (
            viewer_id is not None
            and current_player_id == viewer_id
            and self.status == "running"
        ):
            viewer_index = self.player_index(viewer_id)
            state["legal_actions"] = self.legal_actions(viewer_index)

        return state

    def player_index(self, player_id: str) -> int:
        """Return the seat index for a player identifier.

        Args:
            player_id (str): Player identifier.

        Returns:
            int: Zero-based seat index.
        """
        for index, seat in enumerate(self.players):
            if seat.player_id == player_id:
                return index
        raise InvalidActionError(f"Unknown player_id '{player_id}'")

    def is_round_complete(self) -> bool:
        """Return whether the current betting round is complete.

        Returns:
            bool: True when no active player has pending action.
        """
        for seat in self.players:
            if seat.folded or seat.all_in:
                continue
            if not seat.acted:
                return False
            if seat.committed != self.current_bet:
                return False
        return True

    def legal_actions(self, actor_index: int) -> List[str]:
        """Return legal actions for the acting player.

        Args:
            actor_index (int): Index of the acting player.

        Returns:
            List[str]: Available action names.
        """
        seat = self.players[actor_index]
        to_call = max(0, self.current_bet - seat.committed)

        actions = ["fold"]
        if to_call == 0:
            actions.append("check")
            if seat.stack > 0:
                actions.append("bet")
        else:
            actions.append("call")

        if seat.stack > to_call and self.current_bet > 0:
            actions.append("raise_to")
        return actions

    def min_raise_to(self, actor_index: int) -> int:
        """Return the minimum valid raise target.

        Args:
            actor_index (int): Index of the acting player.

        Returns:
            int: Minimum raise target amount.
        """
        seat = self.players[actor_index]
        to_call = max(0, self.current_bet - seat.committed)
        if to_call == 0:
            return max(self.big_blind, self.current_bet + self.big_blind)
        return self.current_bet + max(self.big_blind, self.min_raise_size)

    def commit(self, player_index: int, amount: int) -> int:
        """Move chips from a player stack into the pot.

        Args:
            player_index (int): Index of the player placing chips.
            amount (int): Requested chip amount.

        Returns:
            int: Actual amount committed.
        """
        seat = self.players[player_index]
        actual = min(amount, seat.stack)
        seat.stack -= actual
        seat.committed += actual
        self.pot += actual
        if seat.stack == 0:
            seat.all_in = True
        return actual

    def next_eligible_player(self, from_index: int) -> Optional[int]:
        """Return the next active player after a seat index.

        Args:
            from_index (int): Seat index used as the starting point.

        Returns:
            Optional[int]: Next active player index, if any.
        """
        count = len(self.players)
        for offset in range(1, count):
            index = (from_index + offset) % count
            seat = self.players[index]
            if not seat.folded and not seat.all_in:
                return index
        return None

    def next_eligible_from(self, start_index: int) -> Optional[int]:
        """Return the first active player at or after a seat index.

        Args:
            start_index (int): Seat index used as the starting point.

        Returns:
            Optional[int]: Active player index, if any.
        """
        count = len(self.players)
        for offset in range(count):
            index = (start_index + offset) % count
            seat = self.players[index]
            if not seat.folded and not seat.all_in:
                return index
        return None

    def remaining_players(self) -> int:
        """Return the number of players who have not folded.

        Returns:
            int: Count of non-folded players.
        """
        return sum(1 for seat in self.players if not seat.folded)

    def all_remaining_all_in(self) -> bool:
        """Return whether all non-folded players are all-in.

        Returns:
            bool: True when every remaining player has no chips behind.
        """
        active = [seat for seat in self.players if not seat.folded]
        if len(active) <= 1:
            return False
        return all(seat.all_in for seat in active)

    def reset_acted_flags_after_aggression(self, aggressor_index: int) -> None:
        """Reset acted flags after a bet or raise.

        Args:
            aggressor_index (int): Seat index of the aggressor.

        Returns:
            None: This method does not return a value.
        """
        for index, seat in enumerate(self.players):
            if seat.folded or seat.all_in:
                continue
            seat.acted = index == aggressor_index

    def deal_board(self, count: int) -> None:
        """Deal cards from the deck to the board.

        Args:
            count (int): Number of cards to deal.

        Returns:
            None: This method does not return a value.
        """
        for _ in range(count):
            self.board.append(self.deck.pop())

    def blind_positions(self) -> tuple[int, int, int]:
        """Calculate small blind, big blind, and first-to-act positions.

        Returns:
            tuple[int, int, int]: Blind and first-to-act indices.
        """
        count = len(self.players)
        dealer = self.dealer_index

        if count == 2:
            small_blind = dealer
            big_blind = (dealer + 1) % count
            first_to_act = small_blind
            return small_blind, big_blind, first_to_act

        small_blind = (dealer + 1) % count
        big_blind = (dealer + 2) % count
        first_to_act = (dealer + 3) % count
        return small_blind, big_blind, first_to_act

    def first_to_act_postflop(self) -> int:
        """Return the first player to act on post-flop streets.

        Returns:
            int: Seat index for first action.
        """
        return (self.dealer_index + 1) % len(self.players)
