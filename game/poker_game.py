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

    def run_hand(self):
        self.preflop()
        self.flop()
        self.turn()
        self.river()

    def distribute_cards(self):
        """Distributes two cards to every player, and five to the board (unrevealed)."""
        for actor in self.players:
            actor.add_card(self.deck.draw_card())
            actor.add_card(self.deck.draw_card())

        for _ in range(5):
            self.board.add_card(self.deck.draw_card())

    def preflop(self):
        self._play_blind(self.small_blind_amount)
        self._play_blind(self.big_blind_amount)
        self.distribute_cards()
        self._play_round_until_settled()
        self._reset_street_data(next_street="flop")

    def flop(self):
        for _ in range(3):
            self.board.reveal_card()
        self._play_round_until_settled()
        self._reset_street_data(next_street="turn")

    def turn(self):
        self.board.reveal_card()
        self._play_round_until_settled()
        self._reset_street_data(next_street="river")

    def river(self):
        self.board.reveal_card()
        self._play_round_until_settled()
        self._end_game()

    def _play_round_until_settled(self):
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
        active = [actor for actor in self.players if not actor.is_folded and not actor.is_all_in]
        if len(active) <= 1:
            return False
        return any(actor.can_play_turn(self.call_amount) for actor in active)

    def _register_player_move(self, player_move):
        current_registry = {
            "preflop": self.preflop_moves,
            "flop": self.flop_moves,
            "turn": self.turn_moves,
            "river": self.river_moves,
        }[self.curr_street]
        current_registry.append(player_move)

    def _reset_street_data(self, next_street):
        for actor in self.players:
            actor.reset_street()
        self.call_amount = 0
        self.turn_index = 0
        self.curr_street = next_street

    def _play_blind(self, blind_amount):
        current_player = self.players[self.turn_index]
        move = (current_player.player_id, "blind", blind_amount)
        self.preflop_moves.append(move)

        self.pot += blind_amount
        current_player.play_blind(blind_amount)
        self.call_amount = max(self.call_amount, current_player.curr_bet_amount)

        self._increment_turn_index()

    def _increment_turn_index(self):
        self.turn_index = (self.turn_index + 1) % len(self.players)

    def _get_curr_player(self):
        return self.players[self.turn_index]

    def _get_game_state_dict(self):
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
        self.curr_street = "showdown"

