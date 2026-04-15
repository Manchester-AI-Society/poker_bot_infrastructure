from .poker_card import pokerCard

class pokerBoard:
    def __init__(self):
        """Initialises an empty decks with no cards."""
        self.cards = []
        self.revealed_cards = 0
    
    def add_card(self, card: pokerCard):
        """Adds a card to the deck"""
        assert len(self.cards) < 5
        self.cards.append(card)

    def add_cards(self, cards):
        """Adds multiple hidden cards to the board."""
        assert len(self.cards) < 5
        for card in cards:
            self.add_card(card)
    
    def reveal_card(self):
        """Increases number of revealed cards by one"""
        assert self.revealed_cards < len(self.cards)
        self.revealed_cards += 1

    def reveal_cards(self, count: int):
        """Reveals multiple cards in sequence."""
        if count < 0:
            raise ValueError("count must be non-negative")
        for _ in range(count):
            self.reveal_card()
    
    def get_revealed_cards(self):
        """Returns a list of all the cards that have been revealed so far"""
        return self.cards[:self.revealed_cards]

    def get_revealed_cards_str(self):
        """Returns revealed board cards as string identifiers."""
        cards = self.get_revealed_cards()
        card_strs = []
        for card in cards:
            card_strs.append(card.get_str())
        return card_strs