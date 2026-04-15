from __future__ import annotations

from typing import Iterable, List


CARD_MIN_NUMBER = 1
CARD_MAX_NUMBER = 13
CARD_SUIT_NAMES = ("spades", "clubs", "hearts", "diamonds")

RANKS = "23456789TJQKA"
SUITS = "SHDC"
RANK_TO_VALUE = {rank: index for index, rank in enumerate(RANKS, start=2)}

_SUIT_TO_CODE = {
    "spades": "S",
    "clubs": "C",
    "hearts": "H",
    "diamonds": "D",
}

_RANK_TO_CODE = {
    1: "A",
    10: "T",
    11: "J",
    12: "Q",
    13: "K",
}


class pokerCard:
    def __init__(self, card_number: int, card_suit: str):
        """
        Creates a new poker card object.
        
        Parameters
        ----------
        card_number: int 
            The card number (between 1-13). 
                card_number = 1: Ace
                card_number = 11: Jack
                card_number = 12: Queen
                card_number = 13: King
        
        card_suit: str
            One of ("spades", "clubs", "hearts", "diamonds")
        """

        assert CARD_MIN_NUMBER <= card_number <= CARD_MAX_NUMBER
        assert card_suit in CARD_SUIT_NAMES

        self.card_number = card_number
        self.card_suit = card_suit

    def get_card_colour(self):
        """Returns the colour of the current card as a string ["black", "red"]"""

        if self.card_suit in ["spades", "clubs"]:
            return "black"
        return "red"

    def get_str(self):
        return f"{self.card_suit}_{self.card_number}"


def card_to_code(card: pokerCard) -> str:
    """Convert a card object to evaluator/API card code."""
    rank_code = _RANK_TO_CODE.get(card.card_number, str(card.card_number))
    suit_code = _SUIT_TO_CODE[card.card_suit]
    return f"{rank_code}{suit_code}"


def cards_to_codes(cards: Iterable[pokerCard]) -> List[str]:
    """Convert a list of cards to card code strings."""
    return [card_to_code(card) for card in cards]
