from poker_hand import pokerHand
from poker_card import pokerCard

class player:
    def __init__(self, current_balance : int):
        """Initializes a player object with balance float current_balance in GBP"""
        
        self.card1 = None
        self.card2 = None

        self.current_balance = current_balance
        
        self.is_folded = False
    
    def add_card(self, card : pokerCard):
        """Adds a card to the hand"""
        assert not self.card2
    
        if not self.card1:
            self.card1 = card
        else:
            self.card2 = card 

