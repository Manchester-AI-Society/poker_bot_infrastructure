from __future__ import annotations

from .player import Player
from .poker_board import PokerBoard
from .poker_deck import PokerDeck


class PokerGame:
    """Lightweight standalone poker hand runner built on game primitives."""

    def __init__(
        self,
        players: list[Player],
        big_blind_amount: float,
        small_blind_amount: float,
    ):
        """Initialises a game engine for a single poker hand."""
        if len(players) < 2:
            raise ValueError("At least two players are required")
        if small_blind_amount >= big_blind_amount:
            raise ValueError(
                "big_blind_amount must be greater than small_blind_amount"
            )

        self.players = players
        self.pot = 0
        self.curr_street = "preflop"
        self.turn_index = 0
        self.call_amount = 0

        self.small_blind_amount = small_blind_amount
        self.big_blind_amount = big_blind_amount

        self.deck = PokerDeck()
        self.board = PokerBoard()

        self.preflop_moves = []

    def reset_hand(self):
        """Resets hand-scoped state while preserving player balances."""
        self.pot = 0
        self.curr_street = "preflop"
        self.turn_index = 0
        self.call_amount = 0

        self.deck = PokerDeck()
        self.board = PokerBoard()

        self.preflop_moves = []

        for actor in self.players:
            actor.reset_for_new_hand()

    def start_hand(self):
        """Initialises a hand without auto-playing betting rounds."""
        self.reset_hand()
        self._play_blind(self.small_blind_amount)
        self._play_blind(self.big_blind_amount)
        self.distribute_cards()

    def advance_street(self):
        """Advances one street when the current round is settled."""
        progression = {
            "preflop": ("flop", 3),
            "flop": ("turn", 1),
            "turn": ("river", 1),
        }
        next_street_data = progression.get(self.curr_street)
        if next_street_data is None:
            self._end_game()
            return

        next_street, reveal_count = next_street_data
        self.board.reveal_cards(reveal_count)
        self._reset_street_data(next_street=next_street)

    def distribute_cards(self):
        """Deals two cards per player and five board cards."""
        for actor in self.players:
            actor.add_card(self.deck.draw_card())
            actor.add_card(self.deck.draw_card())

        self.board.add_cards(self.deck.draw_cards(5))

    def round_has_pending_actions(self):
        """Checks whether any active player still has a pending action."""
        active = [
            actor
            for actor in self.players
            if not actor.is_folded and not actor.is_all_in
        ]
        if len(active) <= 1:
            return False
        return any(actor.can_play_turn(self.call_amount) for actor in active)

    def _reset_street_data(self, next_street):
        """Resets per-street state and advances to the next street."""
        for actor in self.players:
            actor.reset_street()
        self.call_amount = 0
        self.turn_index = 0
        self.curr_street = next_street

    def _play_blind(self, blind_amount):
        """Applies a forced blind and updates the pot state."""
        current_player = self.players[self.turn_index]
        move = (current_player.player_id, "blind", blind_amount)
        self.preflop_moves.append(move)

        self.pot += blind_amount
        current_player.play_blind(blind_amount)
        self.call_amount = max(
            self.call_amount, current_player.curr_bet_amount
        )

        self._increment_turn_index()

    def _increment_turn_index(self):
        """Advances the turn index to the next seat."""
        self.turn_index = (self.turn_index + 1) % len(self.players)

    def _end_game(self):
        """Marks the current hand as finished at showdown."""
        self.curr_street = "showdown"
