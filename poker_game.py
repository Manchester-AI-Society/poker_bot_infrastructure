from player import player
from poker_card import pokerCard
from poker_deck import pokerDeck
from poker_board import pokerBoard

# Example player initialization (4 players with 30 pounds)
players = [player(30.0, player_id) for player_id in range(4)]

class pokerGame:

    def __init__(self, players : list[player], big_blind_amount : float, small_blind_amount : float):

        # Player data
        self.players = players
        self.current_player_bids = [0 for _ in self.players]
        self.remaining_players = len(self.players)

        # Blind amount data
        self.small_blind_amount = small_blind_amount
        self.big_blind_amount = big_blind_amount

        # Card data
        self.deck = pokerDeck()
        self.board = pokerBoard()

        # Game / Betting round data
        self.current_pot = 0 # Total money on the board
        self.amount_to_call = 0 # Maximum amount a player has bet this round
        self.current_round = "preflop" # Current betting round
        self.turn_index = 0 # The player's whose turn it is to play 

        # Game state data
        self.preflop_moves = []
        self.flop_moves = []
        self.turn_moves = []
        self.river_moves = []

    def get_game_state_dict(self):
        """Returns the game state as a dictionary"""

        board_cards_str = self.board.get_revealed_cards_str()

        return {
            "current_round": self.current_round,
            "current_pit": self.current_pot,
            "revealed_cards": board_cards_str,
            "preflop_moves": self.preflop_moves,
            "flop_moves": self.flop_moves,
            "turn_moves": self.turn_moves,
            "river_moves": self.river_moves
        }

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

    def reset_turn(self):
        self.turn_bid_list = [0 for _ in range]

    def _play_small_blind(self):
        """Current player plays a small blind"""
        small_blind_player = self.players[self.turn_index]
        self.turn_bid_list[self.turn_index] += self.small_blind_amount
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

        if self.players[self.turn_index].is_folded:
            self._next_turn()