from poker_card import pokerCard

class player:
    def __init__(self, current_balance, player_id):
        """Initializes a player object with balance float current_balance in GBP"""
        
        self.cards = []
        self.id = player_id
        self.current_balance = current_balance
        self.is_folded = False
    
    def add_card(self, new_card : pokerCard):
        """Adds a card to the player hand"""
        assert len(self.cards) <= 2
        self.cards.append(new_card)
    
    def make_bet(self, bet):
        """Removes the bet from the player balance"""
        assert self.current_balance >= bet
        self.current_balance -= bet
    
        
        

