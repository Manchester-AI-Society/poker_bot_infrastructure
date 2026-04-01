from poker_card import pokerCard
import random

class pokerDeck:
    def __init__(self):
        """Stores a standard 52 card deck in a list"""

        self.deck_list = []
        for card_number in range(1, 14):
            for card_suit in ["spades", "clubs", "hearts", "diamonds"]:
                new_card = pokerCard(card_number=card_number, card_suit=card_suit)
                self.deck_list.append(new_card)
        
        random.shuffle(self.deck_list)
    
    def draw_card(self):
        """Draws a card from the shuffled deck"""

        assert self.deck_list is not None
        return self.deck_list.pop()
