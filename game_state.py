
class gameState:

    def __init__(self):

        self.preflop_moves = []
        self.flop_moves = []
        self.turn_moves = []
        self.river_moves = []
        
        self.revealed_card_strings = []

        self.current_pot = 0
        self.current_round = "preflop"
    
    def get_dict(self):
        return {
            "current_round": self.current_round,
            "current_pit": self.current_pot,
            "revealed_cards": self.revealed_card_strings,
            "preflop_moves": self.preflop_moves,
            "flop_moves": self.flop_moves,
            "turn_moves": self.turn_moves,
            "river_moves": self.river_moves
        }

