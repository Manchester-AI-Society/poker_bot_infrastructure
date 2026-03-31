import secrets
from typing import List

from .cards import RANKS, SUITS


def new_shuffled_deck() -> List[str]:
    cards = [f"{rank}{suit}" for rank in RANKS for suit in SUITS]
    secrets.SystemRandom().shuffle(cards)
    return cards
