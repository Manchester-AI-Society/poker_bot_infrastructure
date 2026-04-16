from player import player
from poker_deck import pokerDeck
from poker_board import pokerBoard

# Example player initialization (4 players with 30 pounds)
players = [player(30.0, player_id) for player_id in range(4)]

class pokerGame:

    def __init__(self, players : list[player], big_blind_amount : float, small_blind_amount : float):

        # Game data
        self.players = players
        self.pot = 0
        self.curr_street = "preflop"
        self.turn_index = 0

        # Street data
        self.call_amount = 0

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
        """Runs the preflop street of the game."""

        # Plays blinds
        self._play_blind(self.small_blind_amount) # Small blind
        self._play_blind(self.big_blind_amount) # Big blind

        # Distributes the cards to the players and the board
        self.distribute_cards()

        # All players take their turns
        self.play_turn()

        # Initiates the flop street
        self._reset_street_data()
        self.curr_street = "flop"
        self.flop()
    
    def flop(self):
        """Runs the flop street of the game"""

        # Reveals three cards from the board
        for _ in range(3):
            self.board.reveal_card()

        # All players take their turns
        self.play_turn()

        # Initiates the turn street
        self._reset_street_data()
        self.curr_street = "turn"
        self.turn()
    
    def turn(self):
        """Runs the turn street of the game"""

        # Reveals one card from the board
        self.board.reveal_card()

        # All players take their turns
        self.play_turn()

        # Initiates the river street
        self._reset_street_data()
        self.curr_street = "river"
        self.turn()
    
    def river(self):
        """Runs the river street of the game"""

        # Reveals the final card
        self.board.reveal_card()

        # All players take their turns
        self.play_turn()

        # Ends the game
        self._end_game()

    def play_turn(self):
        """Recursive function that has the current player play a turn, and calls the next player."""
        
        curr_player = self._get_curr_player()

        # Base case conditions
        if not curr_player.can_play_turn():
            return

        # Player takes their turn
        game_state_dict = self._get_game_state_dict()
        player_move = curr_player.play_turn(game_state_dict)
        self._register_player_move(player_move)

        # Updates the self.pot parameter
        amount_bet = player_move[2]
        self.pot += amount_bet

        # Updates the self.call_amount parameter
        self.call_amount = max(self.call_amount, curr_player.curr_bet_amount)

        # Plays the next turn
        self._increment_turn_index()
        self.play_turn()

    def _register_player_move(self, player_move):
        """Helper function to register a player move in the appropriate register"""
        curr_registry = {
            "preflop": self.preflop_moves,
            "flop": self.flop_moves,
            "turn": self.turn_moves,
            "river": self.river_moves
        }[self.curr_street]
        curr_registry.append(player_move)

    def _reset_street_data(self):
        """Resets the street data of the players and the global game state"""

        # Resets the data
        for player in self.players:
            player.reset_street()
        self.call_amount = 0

        # Rests turn_index to first player after the dealer (turn_index = 0)
        self.turn_index = 0
        self._increment_turn_index()
    
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
    
    def _increment_turn_index(self, recursion_depth = 1):
        """Helper function to increase self.turn_index"""

        # There is only one player in the game
        if recursion_depth == len(self.players):
            self._end_game()

        # Incremenets the turn_index mod len(players)
        self.turn_index += 1
        self.turn_index %= len(self.players)

        # Recurses through the list if the current player is inactive
        curr_player = self.players[self.turn_index]
        if curr_player.is_folded or curr_player.is_all_in:
            self._increment_turn_index(recursion_depth=recursion_depth+1)
    
    def _get_curr_player(self):
        """Helper function to get the player at index self.turn_index"""
        return self.players[self.turn_index]
    
    def _get_game_state_dict(self):
        """Returns the game state as a dictionary"""

        board_cards_str = self.board.get_revealed_cards_str()

        return {
            "current_round": self.curr_street,
            "call_amount": self.call_amount,
            "current_pot": self.pot,
            "revealed_cards": board_cards_str,
            "preflop_moves": self.preflop_moves,
            "flop_moves": self.flop_moves,
            "turn_moves": self.turn_moves,
            "river_moves": self.river_moves
        }

    def _end_game(self):
        """Sanskriti please work on this"""
        pass