from collections import Counter
from itertools import combinations
from typing import Iterable, List, Optional, Tuple, Callable

from .poker_card import RANK_TO_VALUE


HandScore = Tuple[int, Tuple[int, ...]]
HandResult = Tuple[HandScore, str]


def _straight_high(unique_ranks: List[int]) -> Optional[int]:
    if len(unique_ranks) != 5:
        return None

    ordered = sorted(unique_ranks)
    if ordered == [2, 3, 4, 5, 14]:
        return 5
    if ordered[-1] - ordered[0] == 4:
        return ordered[-1]
    return None


def _analyze(cards: Iterable[str]):
    ranks = [RANK_TO_VALUE[c[0]] for c in cards]
    suits = [c[1] for c in cards]

    counter = Counter(ranks)
    groups = sorted(counter.items(), key=lambda x: (x[1], x[0]), reverse=True)

    return {
        "ranks": ranks,
        "groups": groups,
        "counts": sorted(counter.values(), reverse=True),
        "is_flush": len(set(suits)) == 1,
        "straight_high": _straight_high(list(counter.keys())),
    }


# ---- Hand evaluators (each returns tiebreak tuple or None) ---- #

def _straight_flush(data):
    if data["is_flush"] and data["straight_high"] is not None:
        return (data["straight_high"],)


def _four_kind(data):
    if data["counts"] == [4, 1]:
        return (data["groups"][0][0], data["groups"][1][0])


def _full_house(data):
    if data["counts"] == [3, 2]:
        return (data["groups"][0][0], data["groups"][1][0])


def _flush(data):
    if data["is_flush"]:
        return tuple(sorted(data["ranks"], reverse=True))


def _straight(data):
    if data["straight_high"] is not None:
        return (data["straight_high"],)


def _three_kind(data):
    if data["counts"] == [3, 1, 1]:
        triple = data["groups"][0][0]
        kickers = sorted([g[0] for g in data["groups"][1:]], reverse=True)
        return (triple, *kickers)


def _two_pair(data):
    if data["counts"] == [2, 2, 1]:
        pairs = sorted([g[0] for g in data["groups"][:2]], reverse=True)
        kicker = data["groups"][2][0]
        return (*pairs, kicker)


def _one_pair(data):
    if data["counts"] == [2, 1, 1, 1]:
        pair = data["groups"][0][0]
        kickers = sorted([g[0] for g in data["groups"][1:]], reverse=True)
        return (pair, *kickers)


def _high_card(data):
    return tuple(sorted(data["ranks"], reverse=True))


# ---- Rule table (ordered by strength) ---- #

HAND_RULES: List[Tuple[int, str, Callable]] = [
    (8, "Straight Flush", _straight_flush),
    (7, "Four of a Kind", _four_kind),
    (6, "Full House", _full_house),
    (5, "Flush", _flush),
    (4, "Straight", _straight),
    (3, "Three of a Kind", _three_kind),
    (2, "Two Pair", _two_pair),
    (1, "One Pair", _one_pair),
    (0, "High Card", _high_card),
]


def _evaluate_five_card_hand(cards: Iterable[str]) -> HandResult:
    data = _analyze(cards)

    for rank_value, name, fn in HAND_RULES:
        tiebreak = fn(data)
        if tiebreak is not None:
            return (rank_value, tiebreak), name

    raise RuntimeError("Unreachable")


def evaluate_best_hand(cards: List[str]) -> HandResult:
    best_score: Optional[HandScore] = None
    best_name = "High Card"

    for combo in combinations(cards, 5):
        score, name = _evaluate_five_card_hand(combo)
        if best_score is None or score > best_score:
            best_score = score
            best_name = name

    return (best_score or (0, tuple())), best_name