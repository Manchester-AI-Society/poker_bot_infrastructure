"""Turns a bot's Response into the engine's action names."""

from __future__ import annotations

from typing import Optional, Tuple

from .models import Action, GameState


def translate_action(
    action: Action, state: GameState
) -> Tuple[str, Optional[int]]:
    """Converts an SDK action to an engine action and amount.

    Args:
        action (Action): SDK action (fold/call/raise).
        state (GameState): State the action applies to.

    Returns:
        Tuple[str, Optional[int]]: Engine action name and optional amount.
    """
    if action.action_type == "fold":
        return "fold", None

    if action.action_type == "all_in":
        biggest = state.max_raise_to
        if biggest and (
            "bet" in state.legal_actions or "raise_to" in state.legal_actions
        ):
            name = "bet" if "bet" in state.legal_actions else "raise_to"
            return name, biggest
        # Nothing left to raise with: the most you can do is call.
        return ("check", None) if state.call_amount == 0 else ("call", None)

    if action.action_type == "call":
        if state.call_amount == 0:
            return "check", None
        return "call", None

    # Trust the engine's menu when present: at the big-blind option the
    # call amount is 0 but only raise_to is legal.
    if "bet" in state.legal_actions:
        return "bet", action.amount
    if "raise_to" in state.legal_actions:
        return "raise_to", action.amount
    if state.call_amount == 0:
        return "bet", action.amount
    return "raise_to", action.amount
