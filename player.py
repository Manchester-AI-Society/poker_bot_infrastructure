from poker_hand import pokerHand

class player:
    def __init__(self, current_balance):
        """Initializes a player object with balance float current_balance in GBP"""
        
        self.hand = pokerHand()
        self.current_balance = current_balance
