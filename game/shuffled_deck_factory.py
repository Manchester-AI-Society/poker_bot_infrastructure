import secrets
from typing import List

from .cards import RANKS, SUITS


def new_shuffled_deck() -> List[str]:
    """Creates a shuffled poker deck.

    Args:
        None: This function does not take external arguments.

    Returns:
        List[str]: Shuffled list of card codes.
    """
    cards = [f"{rank}{suit}" for rank in RANKS for suit in SUITS]
    secrets.SystemRandom().shuffle(cards)
    return cards
