import random

from .poker_card import (
    CARD_MAX_NUMBER,
    CARD_MIN_NUMBER,
    CARD_SUIT_NAMES,
    PokerCard,
)


class PokerDeck:
    def __init__(self):
        """Stores a standard 52 card deck in a list"""

        self.deck_list = []
        for card_number in range(CARD_MIN_NUMBER, CARD_MAX_NUMBER + 1):
            for card_suit in CARD_SUIT_NAMES:
                new_card = PokerCard(
                    card_number=card_number, card_suit=card_suit
                )
                self.deck_list.append(new_card)

        random.shuffle(self.deck_list)

    def draw_card(self):
        """Draws a card from the shuffled deck"""
        if not self.deck_list:
            raise RuntimeError("Cannot draw from an empty deck")
        return self.deck_list.pop()

    def draw_cards(self, count: int):
        """Draws multiple cards from the deck."""
        if count < 0:
            raise ValueError("count must be non-negative")
        if len(self.deck_list) < count:
            raise RuntimeError("Cannot draw more cards than remaining in deck")
        return [self.draw_card() for _ in range(count)]
