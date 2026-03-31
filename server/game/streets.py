from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from .deck import new_shuffled_deck
from .evaluator import evaluate_best_hand
from .models import MatchState, PlayerSeat


class GameStreetMixin:
    def _start_hand(self, match: MatchState) -> List[Dict[str, Any]]:
        match.status = "running"
        match.street = "preflop"
        match.pot = 0
        match.board = []
        match.current_bet = 0
        match.turn_id = 0
        match.min_raise_size = match.big_blind
        match.deck = new_shuffled_deck()

        for player in match.players:
            player.hole_cards = []
            player.committed = 0
            player.folded = False
            player.all_in = player.stack == 0
            player.acted = False

        for _ in range(2):
            for player in match.players:
                player.hole_cards.append(match.deck.pop())

        sb_index, bb_index, first_to_act = self._blind_positions(match)
        sb_amount = self._commit(match, sb_index, match.small_blind)
        bb_amount = self._commit(match, bb_index, match.big_blind)
        match.current_bet = max(
            match.players[sb_index].committed,
            match.players[bb_index].committed,
        )

        for player in match.players:
            player.acted = False

        match.acting_index = self._next_eligible_from(match, first_to_act)

        blind_events = [
            {
                "type": "action",
                "match_id": match.match_id,
                "player_id": match.players[sb_index].player_id,
                "action": "post_small_blind",
                "amount": sb_amount,
            },
            {
                "type": "action",
                "match_id": match.match_id,
                "player_id": match.players[bb_index].player_id,
                "action": "post_big_blind",
                "amount": bb_amount,
            },
        ]

        self._log_event(
            match,
            "hand_started",
            {"dealer": match.players[match.dealer_index].player_id},
        )
        return blind_events

    def _advance_street(self, match: MatchState) -> Optional[Dict[str, Any]]:
        for player in match.players:
            player.committed = 0
            player.acted = False
        match.current_bet = 0
        match.min_raise_size = match.big_blind

        if match.street == "preflop":
            match.street = "flop"
            self._deal_board(match, 3)
        elif match.street == "flop":
            match.street = "turn"
            self._deal_board(match, 1)
        elif match.street == "turn":
            match.street = "river"
            self._deal_board(match, 1)
        elif match.street == "river":
            match.street = "showdown"
            return self._settle_showdown(match)
        else:
            return self._settle_showdown(match)

        first_to_act = self._first_to_act_postflop(match)
        match.acting_index = self._next_eligible_from(match, first_to_act)

        self._log_event(
            match,
            "street_advanced",
            {"street": match.street, "board": list(match.board)},
        )
        return None

    def _runout_and_showdown(self, match: MatchState) -> Dict[str, Any]:
        while match.street != "showdown":
            showdown = self._advance_street(match)
            if showdown is not None:
                return showdown
        return self._settle_showdown(match)

    def _settle_fold_win(self, match: MatchState) -> Dict[str, Any]:
        winner = next(player for player in match.players if not player.folded)
        winnings = match.pot
        winner.stack += winnings

        results = []
        for player in match.players:
            results.append(
                {
                    "player_id": player.player_id,
                    "hand": "Won by Fold"
                    if player.player_id == winner.player_id
                    else "Folded",
                    "winnings": winnings
                    if player.player_id == winner.player_id
                    else 0,
                }
            )

        match.status = "finished"
        match.street = "showdown"
        match.acting_index = None
        match.pot = 0
        self._log_event(match, "showdown", {"results": results})
        return {
            "type": "showdown",
            "match_id": match.match_id,
            "results": results,
        }

    def _settle_showdown(self, match: MatchState) -> Dict[str, Any]:
        contenders = [player for player in match.players if not player.folded]
        scored: List[Tuple[PlayerSeat, Tuple[int, Tuple[int, ...]], str]] = []

        for player in contenders:
            score, hand_name = evaluate_best_hand(
                player.hole_cards + match.board
            )
            scored.append((player, score, hand_name))

        scored.sort(key=lambda item: item[1], reverse=True)
        best_score = scored[0][1]
        winners = [entry for entry in scored if entry[1] == best_score]

        split = match.pot // len(winners)
        remainder = match.pot % len(winners)

        for index, (player, _, _) in enumerate(winners):
            payout = split + (1 if index < remainder else 0)
            player.stack += payout

        winner_rank_by_id = {
            entry[0].player_id: index for index, entry in enumerate(winners)
        }
        winner_ids = set(winner_rank_by_id.keys())
        results = []
        for player, _, hand_name in scored:
            payout = split
            if player.player_id in winner_ids:
                winner_rank = winner_rank_by_id[player.player_id]
                payout += 1 if winner_rank < remainder else 0
            else:
                payout = 0
            results.append(
                {
                    "player_id": player.player_id,
                    "hand": hand_name,
                    "winnings": payout,
                }
            )

        for player in match.players:
            if player.folded:
                results.append(
                    {
                        "player_id": player.player_id,
                        "hand": "Folded",
                        "winnings": 0,
                    }
                )

        match.status = "finished"
        match.street = "showdown"
        match.acting_index = None
        match.pot = 0
        self._log_event(match, "showdown", {"results": results})
        return {
            "type": "showdown",
            "match_id": match.match_id,
            "results": results,
            "board": list(match.board),
        }

    def _deal_board(self, match: MatchState, count: int) -> None:
        for _ in range(count):
            match.board.append(match.deck.pop())

    def _blind_positions(self, match: MatchState) -> Tuple[int, int, int]:
        count = len(match.players)
        dealer = match.dealer_index

        if count == 2:
            small_blind = dealer
            big_blind = (dealer + 1) % count
            first_to_act = small_blind
            return small_blind, big_blind, first_to_act

        small_blind = (dealer + 1) % count
        big_blind = (dealer + 2) % count
        first_to_act = (dealer + 3) % count
        return small_blind, big_blind, first_to_act

    def _first_to_act_postflop(self, match: MatchState) -> int:
        return (match.dealer_index + 1) % len(match.players)
