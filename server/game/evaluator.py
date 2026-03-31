from collections import Counter
from itertools import combinations
from typing import Iterable, List, Optional, Tuple

from .cards import RANK_TO_VALUE


def _straight_high(unique_ranks: List[int]) -> Optional[int]:
    if len(unique_ranks) != 5:
        return None

    ordered = sorted(unique_ranks)
    if ordered == [2, 3, 4, 5, 14]:
        return 5
    if ordered[-1] - ordered[0] == 4 and len(set(ordered)) == 5:
        return ordered[-1]
    return None


def _evaluate_five_card_hand(
    cards: Iterable[str],
) -> Tuple[Tuple[int, Tuple[int, ...]], str]:
    ranks = [RANK_TO_VALUE[card[0]] for card in cards]
    suits = [card[1] for card in cards]
    rank_counter = Counter(ranks)

    counts = sorted(rank_counter.values(), reverse=True)
    groups = sorted(
        rank_counter.items(), key=lambda item: (item[1], item[0]), reverse=True
    )
    is_flush = len(set(suits)) == 1
    straight_high = _straight_high(list(rank_counter.keys()))

    if is_flush and straight_high is not None:
        return (8, (straight_high,)), "Straight Flush"

    if counts == [4, 1]:
        four_rank = groups[0][0]
        kicker = groups[1][0]
        return (7, (four_rank, kicker)), "Four of a Kind"

    if counts == [3, 2]:
        return (6, (groups[0][0], groups[1][0])), "Full House"

    if is_flush:
        return (5, tuple(sorted(ranks, reverse=True))), "Flush"

    if straight_high is not None:
        return (4, (straight_high,)), "Straight"

    if counts == [3, 1, 1]:
        triple = groups[0][0]
        kickers = sorted([groups[1][0], groups[2][0]], reverse=True)
        return (3, (triple, *kickers)), "Three of a Kind"

    if counts == [2, 2, 1]:
        pair_ranks = sorted([groups[0][0], groups[1][0]], reverse=True)
        kicker = groups[2][0]
        return (2, (pair_ranks[0], pair_ranks[1], kicker)), "Two Pair"

    if counts == [2, 1, 1, 1]:
        pair_rank = groups[0][0]
        kickers = sorted(
            [groups[1][0], groups[2][0], groups[3][0]], reverse=True
        )
        return (1, (pair_rank, *kickers)), "One Pair"

    return (0, tuple(sorted(ranks, reverse=True))), "High Card"


def evaluate_best_hand(
    cards: List[str],
) -> Tuple[Tuple[int, Tuple[int, ...]], str]:
    best_score: Optional[Tuple[int, Tuple[int, ...]]] = None
    best_name = "High Card"

    for combo in combinations(cards, 5):
        score, name = _evaluate_five_card_hand(combo)
        if best_score is None or score > best_score:
            best_score = score
            best_name = name

    if best_score is None:
        return (0, tuple()), best_name
    return best_score, best_name
