from player import player
from poker_card import pokerCard
from poker_deck import pokerDeck
from poker_board import pokerBoard

# Example player initialization (4 players with 30 pounds)
players = [player(30.0, player_id) for player_id in range(4)]

class pokerGame:

    def __init__(self, players : list[player], big_blind_amount : float, small_blind_amount : float):

        # Game data
        self.players = players
        self.current_pot = 0
        self.curr_street = "preflop"

        # Street data
        self.call_amount = 0
        self.turn_index = 0
        self.remaining_players = len(self.players)

        # Blind amount data
        self.small_blind_amount = small_blind_amount
        self.big_blind_amount = big_blind_amount

        # Card data
        self.deck = pokerDeck()
        self.board = pokerBoard()

        # Game state data
        self.preflop_moves = []
        self.flop_moves = []
        self.turn_moves = []
        self.river_moves = []

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

        self._play_blind(self.big_blind_amount) # Plays big blind
        self._play_blind(self.small_blind_amount) # Plays small blind

        self.play_turn()
 
    def play_turn(self):
        """
        Recursive function that has the current player play a turn, and calls the next player.
        
        """
        
        curr_player = self._get_curr_player()

        # Base case conditions
        if self.remaining_players == 1:
            return self._end_game()
        if not curr_player.can_play_turn():
            return

        # Player takes their turn
        game_state_dict = self._get_game_state_dict()
        player_move = curr_player.play_turn(game_state_dict)
        self._register_player_move(player_move)

    def _register_player_move(self, player_move):
        """Helper function to register a player move in the appropriate register"""
        curr_registry = {
            "preflop": self.preflop_moves,
            "flop": self.flop_moves,
            "turn": self.turn_moves,
            "river": self.river_moves
        }[self.curr_street]
        curr_registry.append(player_move)

    def _play_blind(self, blind_amount):
        """Current player plays a small blind"""

        # Fetches player information
        curr_player = self.players[self.turn_index]
        player_id = curr_player.player_id

        # Logs the move
        move = (player_id, "blind", blind_amount)
        self.preflop_moves.append(move)
        
        # Plays the blind
        self.pot += self.small_blind_amount
        curr_player.play_blind(self.small_blind_amount)

        self._increment_turn_index()
    
    
    def _increment_turn_index(self):
        """Helper function to increase self.turn_index"""
        self.turn_index += 1
        self.turn_index %= len(self.players)

        curr_player = self.players[self.turn_index]
        if curr_player.is_folded or curr_player.is_all_in:
            self._increment_turn_index()
    
    def _get_curr_player(self):
        """Helper function to get the player at index self.turn_index"""
        return self.players[self.turn_index]
    
    def _get_game_state_dict(self):
        """Returns the game state as a dictionary"""

        board_cards_str = self.board.get_revealed_cards_str()

        return {
            "current_round": self.current_round,
            "call_amount": self.call_amount,
            "current_pot": self.current_pot,
            "revealed_cards": board_cards_str,
            "preflop_moves": self.preflop_moves,
            "flop_moves": self.flop_moves,
            "turn_moves": self.turn_moves,
            "river_moves": self.river_moves
        }