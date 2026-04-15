from __future__ import annotations

from typing import Any, Dict, List, Tuple

from .poker_card import cards_to_codes
from .match_runtime import MatchRuntime
from .player import player
from .poker_hand_evaluator import evaluate_best_hand


class ShowdownResolver:
    """Resolves fold wins and showdown payouts for runtime."""

    def settle_fold_win(self, runtime: MatchRuntime) -> Dict[str, Any]:
        winner = next(seat for seat in runtime.players if not seat.is_folded)
        winnings = runtime.engine.pot
        winner.curr_balance += winnings

        results = []
        for seat in runtime.players:
            results.append(
                {
                    "player_id": seat.player_id,
                    "hand": "Won by Fold" if seat.player_id == winner.player_id else "Folded",
                    "winnings": winnings if seat.player_id == winner.player_id else 0,
                }
            )

        runtime.status = "finished"
        runtime.engine.curr_street = "showdown"
        runtime.engine.pot = 0
        runtime.winner_ids = [winner.player_id]

        return {
            "type": "showdown",
            "match_id": runtime.match_id,
            "results": results,
        }

    def settle_showdown(self, runtime: MatchRuntime) -> Dict[str, Any]:
        while runtime.engine.board.revealed_cards < len(runtime.engine.board.cards):
            runtime.engine.board.reveal_card()

        board_codes = cards_to_codes(runtime.engine.board.get_revealed_cards())
        contenders = [seat for seat in runtime.players if not seat.is_folded]
        scored: List[Tuple[player, Tuple[int, Tuple[int, ...]], str]] = []

        for seat in contenders:
            score, hand_name = evaluate_best_hand(
                cards_to_codes(seat.cards) + board_codes
            )
            scored.append((seat, score, hand_name))

        scored.sort(key=lambda item: item[1], reverse=True)
        best_score = scored[0][1]
        winners = [entry for entry in scored if entry[1] == best_score]

        split = runtime.engine.pot // len(winners)
        remainder = runtime.engine.pot % len(winners)

        for index, (seat, _, _) in enumerate(winners):
            payout = split + (1 if index < remainder else 0)
            seat.curr_balance += payout

        winner_rank_by_id = {
            entry[0].player_id: index for index, entry in enumerate(winners)
        }
        winner_ids = set(winner_rank_by_id.keys())

        results = []
        for seat, _, hand_name in scored:
            payout = split
            if seat.player_id in winner_ids:
                rank = winner_rank_by_id[seat.player_id]
                payout += 1 if rank < remainder else 0
            else:
                payout = 0
            results.append(
                {
                    "player_id": seat.player_id,
                    "hand": hand_name,
                    "winnings": payout,
                }
            )

        for seat in runtime.players:
            if seat.is_folded:
                results.append(
                    {
                        "player_id": seat.player_id,
                        "hand": "Folded",
                        "winnings": 0,
                    }
                )

        runtime.status = "finished"
        runtime.engine.curr_street = "showdown"
        runtime.engine.pot = 0
        runtime.winner_ids = list(winner_ids)

        return {
            "type": "showdown",
            "match_id": runtime.match_id,
            "results": results,
            "board": board_codes,
        }
