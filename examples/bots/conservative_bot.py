from __future__ import annotations

from player_sdk.bot_interface import PokerBot
from player_sdk.models import Action, GameState


class ExampleConservativeBot(PokerBot):
    """Simple baseline bot: check/call small prices, otherwise fold."""

    def act(self, game_state: GameState) -> Action:
        if game_state.call_amount == 0:
            return Action.call()

        if game_state.call_amount <= max(1, game_state.my_stack // 10):
            return Action.call()

        if (
            game_state.minimum_raise > 0
            and game_state.my_stack >= game_state.minimum_raise * 4
        ):
            return Action.raise_to(game_state.minimum_raise)

        return Action.fold()
