from __future__ import annotations

from typing import Any, Dict, List, Tuple

from .match_runtime import MatchRuntime
from .player import Player
from .poker_card import cards_to_codes
from .poker_hand_evaluator import evaluate_best_hand


def settle_fold_win(runtime: MatchRuntime) -> Dict[str, Any]:
    """Awards the full pot when all but one player have folded."""
    winner = next(seat for seat in runtime.players if not seat.is_folded)
    winnings = runtime.engine.pot
    winner.curr_balance += winnings

    results = []
    for seat in runtime.players:
        is_winner = seat.player_id == winner.player_id
        results.append(
            {
                "player_id": seat.player_id,
                "hand": "Won by Fold" if is_winner else "Folded",
                "winnings": winnings if is_winner else 0,
            }
        )

    runtime.engine.curr_street = "showdown"
    runtime.engine.pot = 0

    return {
        "type": "showdown",
        "match_id": runtime.match_id,
        "results": results,
    }


def build_pots(players: List[Player]) -> List[Tuple[int, List[Player]]]:
    """Splits the chips committed this hand into main and side pots.

    Every distinct commitment level closes one pot. A pot holds the
    chips each seat put in up to that level (folded seats included, as
    dead money) and is contested only by non-folded seats that reached
    the level. A top slice with a single eligible seat is an uncalled
    bet: that seat simply gets it back.
    """
    levels = sorted(
        {seat.total_committed for seat in players if seat.total_committed}
    )
    pots: List[Tuple[int, List[Player]]] = []
    previous = 0
    for level in levels:
        amount = sum(
            min(seat.total_committed, level)
            - min(seat.total_committed, previous)
            for seat in players
        )
        eligible = [
            seat
            for seat in players
            if not seat.is_folded and seat.total_committed >= level
        ]
        previous = level
        if not eligible:
            # Dead money above every live seat's commitment cannot
            # arise from legal betting, but never lose chips if it does.
            if pots:
                pots[-1] = (pots[-1][0] + amount, pots[-1][1])
            continue
        pots.append((amount, eligible))
    return pots


def _odd_chip_order(
    runtime: MatchRuntime, winners: List[Player]
) -> List[Player]:
    """Orders winners clockwise starting left of the button."""
    seats = len(runtime.players)
    dealer = runtime.engine.dealer_index

    def distance(seat: Player) -> int:
        index = runtime.players.index(seat)
        return (index - dealer - 1) % seats

    return sorted(winners, key=distance)


def settle_showdown(runtime: MatchRuntime) -> Dict[str, Any]:
    """Evaluates remaining hands and distributes showdown payouts.

    Chips are paid pot by pot (main pot, then side pots), so a short
    all-in stack can only win what it was able to match. Odd chips of
    a split pot go to the winner closest to the left of the button.
    """
    board = runtime.engine.board
    while board.revealed_cards < len(board.cards):
        board.reveal_card()

    board_codes = cards_to_codes(runtime.engine.board.get_revealed_cards())
    contenders = [seat for seat in runtime.players if not seat.is_folded]
    scored: List[Tuple[Player, Tuple[int, Tuple[int, ...]], str]] = []

    for seat in contenders:
        score, hand_name = evaluate_best_hand(
            cards_to_codes(seat.cards) + board_codes
        )
        scored.append((seat, score, hand_name))

    scores = {entry[0].player_id: entry[1] for entry in scored}
    winnings: Dict[str, int] = {}
    paid = 0
    for amount, eligible in build_pots(runtime.players):
        best = max(scores[seat.player_id] for seat in eligible)
        winners = _odd_chip_order(
            runtime,
            [seat for seat in eligible if scores[seat.player_id] == best],
        )
        share, remainder = divmod(amount, len(winners))
        for position, seat in enumerate(winners):
            payout = share + (1 if position < remainder else 0)
            seat.curr_balance += payout
            winnings[seat.player_id] = winnings.get(seat.player_id, 0) + payout
        paid += amount

    if paid != runtime.engine.pot:
        raise RuntimeError(
            f"Pot accounting error: paid {paid} of {runtime.engine.pot}"
        )

    scored.sort(key=lambda item: item[1], reverse=True)
    results = [
        {
            "player_id": seat.player_id,
            "hand": hand_name,
            "winnings": winnings.get(seat.player_id, 0),
        }
        for seat, _, hand_name in scored
    ]

    for seat in runtime.players:
        if seat.is_folded:
            results.append(
                {
                    "player_id": seat.player_id,
                    "hand": "Folded",
                    "winnings": 0,
                }
            )

    runtime.engine.curr_street = "showdown"
    runtime.engine.pot = 0

    return {
        "type": "showdown",
        "match_id": runtime.match_id,
        "results": results,
        "board": board_codes,
    }
