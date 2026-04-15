from __future__ import annotations

from .player import player
from .poker_board import pokerBoard
from .poker_deck import pokerDeck


class pokerGame:
    """Lightweight standalone poker hand runner built on game primitives."""

    def __init__(
        self,
        players: list[player],
        big_blind_amount: float,
        small_blind_amount: float,
    ):
        """Initialises a game engine for a single poker hand."""
        if len(players) < 2:
            raise ValueError("At least two players are required")
        if small_blind_amount >= big_blind_amount:
            raise ValueError("big_blind_amount must be greater than small_blind_amount")

        self.players = players
        self.pot = 0
        self.curr_street = "preflop"
        self.turn_index = 0
        self.call_amount = 0

        self.small_blind_amount = small_blind_amount
        self.big_blind_amount = big_blind_amount

        self.deck = pokerDeck()
        self.board = pokerBoard()

        self.preflop_moves = []
        self.flop_moves = []
        self.turn_moves = []
        self.river_moves = []

    def reset_hand(self):
        """Resets hand-scoped state while preserving player balances."""
        self.pot = 0
        self.curr_street = "preflop"
        self.turn_index = 0
        self.call_amount = 0

        self.deck = pokerDeck()
        self.board = pokerBoard()

        self.preflop_moves = []
        self.flop_moves = []
        self.turn_moves = []
        self.river_moves = []

        for actor in self.players:
            actor.reset_for_new_hand()

    def start_hand(self):
        """Initialises a hand without auto-playing betting rounds."""
        self.reset_hand()
        self._play_blind(self.small_blind_amount)
        self._play_blind(self.big_blind_amount)
        self.distribute_cards()

    def round_has_pending_actions(self):
        """Public proxy for round action availability."""
        return self._round_has_pending_actions()

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

    def run_hand(self):
        """Runs a full hand from blinds through showdown."""
        self.start_hand()
        self._play_round_until_settled()
        while self.curr_street != "showdown":
            self.advance_street()
            if self.curr_street == "showdown":
                break
            self._play_round_until_settled()

    def distribute_cards(self):
        """Distributes two cards to every player, and five to the board (unrevealed)."""
        for actor in self.players:
            actor.add_card(self.deck.draw_card())
            actor.add_card(self.deck.draw_card())

        self.board.add_cards(self.deck.draw_cards(5))

    def preflop(self):
        """Runs the preflop stage using the legacy flow."""
        self._play_blind(self.small_blind_amount)
        self._play_blind(self.big_blind_amount)
        self.distribute_cards()
        self._play_round_until_settled()
        self._reset_street_data(next_street="flop")

    def flop(self):
        """Runs the flop stage using the legacy flow."""
        self.board.reveal_cards(3)
        self._play_round_until_settled()
        self._reset_street_data(next_street="turn")

    def turn(self):
        """Runs the turn stage using the legacy flow."""
        self.board.reveal_cards(1)
        self._play_round_until_settled()
        self._reset_street_data(next_street="river")

    def river(self):
        """Runs the river stage using the legacy flow."""
        self.board.reveal_cards(1)
        self._play_round_until_settled()
        self._end_game()

    def _play_round_until_settled(self):
        """Processes player actions until the betting round is complete."""
        while True:
            curr_player = self._get_curr_player()
            if curr_player.is_folded or curr_player.is_all_in:
                self._increment_turn_index()
                if not self._round_has_pending_actions():
                    return
                continue

            if not curr_player.can_play_turn(self.call_amount):
                if not self._round_has_pending_actions():
                    return
                self._increment_turn_index()
                continue

            game_state_dict = self._get_game_state_dict()
            player_move = curr_player.play_turn(game_state_dict)
            self._register_player_move(player_move)

            amount_bet = player_move[2]
            self.pot += amount_bet
            self.call_amount = max(self.call_amount, curr_player.curr_bet_amount)
            curr_player.has_moved = True

            self._increment_turn_index()
            if not self._round_has_pending_actions():
                return

    def _round_has_pending_actions(self):
        """Checks whether any active player still has a pending action."""
        active = [actor for actor in self.players if not actor.is_folded and not actor.is_all_in]
        if len(active) <= 1:
            return False
        return any(actor.can_play_turn(self.call_amount) for actor in active)

    def _register_player_move(self, player_move):
        """Records a player move in the current street history."""
        current_registry = {
            "preflop": self.preflop_moves,
            "flop": self.flop_moves,
            "turn": self.turn_moves,
            "river": self.river_moves,
        }[self.curr_street]
        current_registry.append(player_move)

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
        self.call_amount = max(self.call_amount, current_player.curr_bet_amount)

        self._increment_turn_index()

    def _increment_turn_index(self):
        """Advances the turn index to the next seat."""
        self.turn_index = (self.turn_index + 1) % len(self.players)

    def _get_curr_player(self):
        """Returns the player whose turn index is active."""
        return self.players[self.turn_index]

    def _get_game_state_dict(self):
        """Builds the game-state payload passed to player inference."""
        return {
            "current_round": self.curr_street,
            "call_amount": self.call_amount,
            "current_pot": self.pot,
            "revealed_cards": self.board.get_revealed_cards_str(),
            "preflop_moves": self.preflop_moves,
            "flop_moves": self.flop_moves,
            "turn_moves": self.turn_moves,
            "river_moves": self.river_moves,
        }

    def _end_game(self):
        """Marks the current hand as finished at showdown."""
        self.curr_street = "showdown"

