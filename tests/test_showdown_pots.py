"""Direct tests of pot building and showdown payouts (AUDIT C1, M1)."""

from __future__ import annotations

from typing import Dict, List, Optional

import pytest

from game.match_runtime import MatchRuntime
from game.player import Player
from game.poker_card import PokerCard
from game.poker_game import PokerGame
from game.showdown_resolver import build_pots, settle_showdown

_RANKS = {"A": 1, "T": 10, "J": 11, "Q": 12, "K": 13}
_RANKS.update({str(n): n for n in range(2, 10)})
_SUITS = {"S": "spades", "C": "clubs", "H": "hearts", "D": "diamonds"}


def _cards(codes: str) -> List[PokerCard]:
    return [PokerCard(_RANKS[c[0]], _SUITS[c[1]]) for c in codes.split()]


def table(
    committed: List[int],
    holes: List[Optional[str]],
    board: str,
    *,
    folded: tuple = (),
    dealer: int = 0,
) -> MatchRuntime:
    """Builds a runtime frozen at showdown: only the pot logic runs."""
    players = [Player(0, f"p{i}") for i in range(len(committed))]
    engine = PokerGame(players, big_blind_amount=20, small_blind_amount=10)
    engine.dealer_index = dealer
    engine.pot = sum(committed)
    engine.board.cards = _cards(board)
    for index, (seat, chips) in enumerate(zip(players, committed)):
        seat.total_committed = chips
        seat.is_folded = index in folded
        if holes[index]:
            seat.cards = _cards(holes[index])
    return MatchRuntime(
        match_id="t",
        engine=engine,
        turn_timeout_seconds=1,
        event_log_limit=10,
    )


def payouts(result: dict) -> Dict[str, int]:
    return {r["player_id"]: r["winnings"] for r in result["results"]}


def balances(runtime: MatchRuntime) -> List[int]:
    return [seat.curr_balance for seat in runtime.players]


BOARD = "9H 8C 4D 3S JC"  # nobody improves: pocket pairs / high cards play


def test_build_pots_uncalled_excess_is_its_own_single_seat_pot():
    runtime = table([200, 600], ["AS AD", "7S 2D"], BOARD)
    pots = build_pots(runtime.players)
    assert [(amount, [s.player_id for s in who]) for amount, who in pots] == [
        (400, ["p0", "p1"]),
        (400, ["p1"]),
    ]


def test_folded_chips_stay_in_the_pot_but_the_seat_cannot_win_them():
    runtime = table(
        [100, 300, 300],
        ["AS AD", "KS KD", "7C 2D"],
        BOARD,
        folded=(0,),  # best hand, but folded
    )
    result = settle_showdown(runtime)
    assert payouts(result) == {"p1": 700, "p2": 0, "p0": 0}
    assert balances(runtime) == [0, 700, 0]


def test_three_way_all_in_for_different_amounts_pays_each_pot_separately():
    # p0 100 (best), p1 300 (second), p2 600 (worst).
    runtime = table(
        [100, 300, 600],
        ["AS AD", "KS KD", "QS QD"],
        BOARD,
    )
    result = settle_showdown(runtime)
    assert payouts(result) == {"p0": 300, "p1": 400, "p2": 300}
    assert balances(runtime) == [300, 400, 300]


def test_short_stack_losing_does_not_lose_the_side_pot_for_others():
    # p0 (shortest) has the worst hand; p2 beats p1 for the side pot.
    runtime = table(
        [100, 500, 500],
        ["7S 2D", "KS KD", "AS AD"],
        BOARD,
    )
    result = settle_showdown(runtime)
    assert payouts(result) == {"p2": 1100, "p0": 0, "p1": 0}


def test_one_chip_overbet_is_returned_not_split():
    runtime = table(
        [50, 51],
        ["2S 3D", "2C 3H"],
        "AH AC KD KS QC",
    )
    result = settle_showdown(runtime)
    assert payouts(result) == {"p0": 50, "p1": 51}
    assert sum(balances(runtime)) == 101


def test_odd_chip_goes_left_of_the_button_not_to_the_lowest_seat():
    # p2 folded after posting 11 dead chips: 50+50+11 = 111 split two
    # ways leaves one odd chip. The button is seat 0, so the first
    # winner to its left (p1) takes it, not the lowest seat (p0).
    runtime = table(
        [50, 50, 11],
        ["2S 3D", "2C 3H", None],
        "AH AC KD KS QC",
        folded=(2,),
        dealer=0,
    )
    result = settle_showdown(runtime)
    assert payouts(result) == {"p1": 56, "p0": 55, "p2": 0}


def test_odd_chip_follows_the_button_when_it_moves():
    runtime = table(
        [50, 50, 11],
        ["2S 3D", "2C 3H", None],
        "AH AC KD KS QC",
        folded=(2,),
        dealer=1,  # first winner left of seat 1 is seat 2 (folded) -> p0
    )
    result = settle_showdown(runtime)
    assert payouts(result) == {"p0": 56, "p1": 55, "p2": 0}


@pytest.mark.parametrize("dealer", [0, 1, 2])
def test_chips_are_conserved_for_any_button_position(dealer):
    runtime = table(
        [37, 91, 91],
        ["2S 3D", "2C 3H", "2D 3C"],
        "AH AC KD KS QC",
        dealer=dealer,
    )
    result = settle_showdown(runtime)
    assert sum(payouts(result).values()) == 219
    assert sum(balances(runtime)) == 219
