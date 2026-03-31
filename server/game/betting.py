from __future__ import annotations

from typing import List, Optional, Tuple

from .models import InvalidActionError, MatchState


class GameBettingMixin:
    def _apply_action(
        self,
        match: MatchState,
        actor_index: int,
        action: str,
        amount: Optional[int],
    ) -> Tuple[str, Optional[int]]:
        player = match.players[actor_index]
        to_call = max(0, match.current_bet - player.committed)
        legal = self._legal_actions(match, actor_index)

        if action not in legal:
            raise InvalidActionError(
                f"Illegal action '{action}'. Legal actions: {legal}"
            )

        emitted_amount: Optional[int] = None

        if action == "fold":
            player.folded = True
            player.acted = True
            emitted_amount = None
        elif action == "check":
            if to_call != 0:
                raise InvalidActionError("Cannot check when facing a bet")
            player.acted = True
        elif action == "call":
            call_amount = min(to_call, player.stack)
            self._commit(match, actor_index, call_amount)
            player.acted = True
            emitted_amount = call_amount
        elif action == "bet":
            if amount is None:
                raise InvalidActionError("Bet requires an amount")
            if match.current_bet != 0:
                raise InvalidActionError(
                    "Use raise_to when a bet already exists"
                )
            if amount < match.big_blind:
                raise InvalidActionError(
                    f"Bet must be at least {match.big_blind}"
                )

            target_total = min(player.committed + player.stack, amount)
            placed = target_total - player.committed
            if placed <= 0:
                raise InvalidActionError("Bet amount is too small")

            self._commit(match, actor_index, placed)
            previous_bet = match.current_bet
            match.current_bet = player.committed
            match.min_raise_size = max(
                match.big_blind, match.current_bet - previous_bet
            )
            self._reset_acted_flags_after_aggression(match, actor_index)
            emitted_amount = player.committed
        elif action == "raise_to":
            if amount is None:
                raise InvalidActionError("raise_to requires an amount")
            min_raise_to = self._min_raise_to(match, actor_index)
            max_raise_to = player.committed + player.stack
            if amount < min_raise_to:
                raise InvalidActionError(
                    f"raise_to must be at least {min_raise_to}"
                )
            if amount > max_raise_to:
                raise InvalidActionError(
                    f"raise_to cannot exceed {max_raise_to}"
                )

            commit_amount = amount - player.committed
            self._commit(match, actor_index, commit_amount)
            raise_size = amount - match.current_bet
            match.current_bet = amount
            match.min_raise_size = max(match.big_blind, raise_size)
            self._reset_acted_flags_after_aggression(match, actor_index)
            emitted_amount = amount
        else:
            raise InvalidActionError(f"Unsupported action '{action}'")

        self._log_event(
            match,
            "action",
            {
                "player_id": player.player_id,
                "action": action,
                "amount": emitted_amount,
                "street": match.street,
                "pot": match.pot,
            },
        )
        return action, emitted_amount

    def _is_round_complete(self, match: MatchState) -> bool:
        for player in match.players:
            if player.folded or player.all_in:
                continue
            if not player.acted:
                return False
            if player.committed != match.current_bet:
                return False
        return True

    def _legal_actions(self, match: MatchState, actor_index: int) -> List[str]:
        player = match.players[actor_index]
        to_call = max(0, match.current_bet - player.committed)

        actions = ["fold"]
        if to_call == 0:
            actions.append("check")
            if player.stack > 0:
                actions.append("bet")
        else:
            actions.append("call")

        if player.stack > to_call and match.current_bet > 0:
            actions.append("raise_to")
        return actions

    def _min_raise_to(self, match: MatchState, actor_index: int) -> int:
        player = match.players[actor_index]
        to_call = max(0, match.current_bet - player.committed)
        if to_call == 0:
            return max(match.big_blind, match.current_bet + match.big_blind)
        return match.current_bet + max(match.big_blind, match.min_raise_size)

    def _commit(
        self, match: MatchState, player_index: int, amount: int
    ) -> int:
        player = match.players[player_index]
        actual = min(amount, player.stack)
        player.stack -= actual
        player.committed += actual
        match.pot += actual
        if player.stack == 0:
            player.all_in = True
        return actual

    def _next_eligible_player(
        self, match: MatchState, from_index: int
    ) -> Optional[int]:
        count = len(match.players)
        for offset in range(1, count):
            index = (from_index + offset) % count
            player = match.players[index]
            if not player.folded and not player.all_in:
                return index
        return None

    def _next_eligible_from(
        self, match: MatchState, start_index: int
    ) -> Optional[int]:
        count = len(match.players)
        for offset in range(count):
            index = (start_index + offset) % count
            player = match.players[index]
            if not player.folded and not player.all_in:
                return index
        return None

    def _remaining_players(self, match: MatchState) -> int:
        return sum(1 for player in match.players if not player.folded)

    def _all_remaining_all_in(self, match: MatchState) -> bool:
        active = [player for player in match.players if not player.folded]
        if len(active) <= 1:
            return False
        return all(player.all_in for player in active)

    def _reset_acted_flags_after_aggression(
        self, match: MatchState, aggressor_index: int
    ) -> None:
        for index, player in enumerate(match.players):
            if player.folded or player.all_in:
                continue
            player.acted = index == aggressor_index
