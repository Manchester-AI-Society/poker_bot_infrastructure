from player import player
from poker_card import pokerCard
from poker_deck import pokerDeck
from poker_board import pokerBoard

class pokerGame:

    def __init__(self, num_players, big_blind_amount, small_blind_amount):
        self.players = [player() for _ in range(num_players)]
        self.deck = pokerDeck()
        self.board = pokerBoard()
        self.pot = 0

        self.turn_index = 0
        self.small_blind_amount = small_blind_amount
        self.big_blind_amount = big_blind_amount

    def distribute_cards(self):
        """Distributes two cards to every player, and 5 to the board (unrevealed)"""

        # Distributes player cards
        for player in self.players:
            new_card1 = self.deck.draw_card()
            new_card2 = self.deck.draw_card()

            player.add_card(new_card1)
            player.add_card(new_card2)
        
        # Distributes board cards
        for _ in range(5):
            new_card = self.deck.draw_card()
            self.board.add_card(new_card)
    
    def preflop(self):
        """Runs the preflop turn of the game."""

        self._play_small_blind()
        self._play_big_blind()

        
    def _play_small_blind(self):
        """Current player plays a small blind"""
        small_blind_player = self.players[self.turn_index]
        self.pot += self.small_blind_amount
        small_blind_player.make_bet(self.small_blind_amount)
        self._next_turn()
    
    def _play_big_blind(self):
        """Current player plays a big blind"""
        big_blind_player = self.players[self.turn_index]
        self.pot += self.big_blind_amount
        big_blind_player.make_bet(self.big_blind_amount)
        self._next_turn()
    
    def _next_turn(self):
        """Helper function to increase self.turn_index"""
        self.turn_index += 1
        self.turn_index %= len(self.players)