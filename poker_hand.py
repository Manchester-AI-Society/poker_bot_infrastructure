from poker_card import pokerCard

class pokerHand:
    def __init__(self):
        """Initializes an empty poker hand"""
        self.card1 = None
        self.card2 = None
    
    def add_card(self, card : pokerCard):
        """Adds a card to the hand"""
        assert not self.card2
        if not self.card1:
            self.card1 = card
        else:
            self.card2 = card
        
