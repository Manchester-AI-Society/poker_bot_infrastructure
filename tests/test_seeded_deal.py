"""Seeded shuffles make deals reproducible (AUDIT H7)."""

from __future__ import annotations

import random

from game.player import Player
from game.poker_card import cards_to_codes
from game.poker_deck import PokerDeck
from game.poker_game import PokerGame


def _deal(seed):
    players = [Player(1000, "a"), Player(1000, "b")]
    rng = None if seed is None else random.Random(seed)
    engine = PokerGame(players, 20, 10, rng=rng)
    engine.start_hand()
    return (
        [cards_to_codes(p.cards) for p in players],
        cards_to_codes(engine.board.cards),
    )


def test_same_seed_gives_the_same_deal():
    assert _deal(123) == _deal(123)


def test_different_seeds_give_different_deals():
    assert _deal(1) != _deal(2)


def test_seeded_engine_deals_a_different_hand_each_hand_but_replays():
    def two_hands(seed):
        players = [Player(1000, "a"), Player(1000, "b")]
        engine = PokerGame(players, 20, 10, rng=random.Random(seed))
        engine.start_hand()
        first = cards_to_codes(engine.board.cards)
        engine.start_hand()
        return first, cards_to_codes(engine.board.cards)

    first, second = two_hands(7)
    assert first != second
    assert two_hands(7) == (first, second)


def test_unseeded_decks_still_differ():
    decks = {tuple(cards_to_codes(PokerDeck().deck_list)) for _ in range(5)}
    assert len(decks) > 1


def test_deck_contains_52_unique_cards():
    codes = cards_to_codes(PokerDeck(random.Random(0)).deck_list)
    assert len(codes) == len(set(codes)) == 52
