from poker_card import pokerCard

class pokerDeck:
    def __init__(self):
        """Initializes an empty decks with no cards."""
        self.cards = []
        self.revealed_cards = 0
    
    def add_card(self, card : pokerCard):
        """Adds a card to the deck"""
        assert len(self.cards) < 5
        self.cards.append(card)
    
    def reveal_card(self):
        """Increases number of revealed cards by one"""
        assert self.revealed_cards <= len(self.cards)
        self.revealed_cards += 1
    
    def get_revealed_cards(self):
        """Returns a list of all the cards that have been revealed so far"""
        return self.cards[:self.revealed_cards]