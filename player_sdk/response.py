"""Checks a bot's response against the rules before it is played.

The arena runs this in the bot's own process, so a mistake is reported with a
plain sentence naming what was wrong and what was allowed, and lands in the
team's private log, instead of surfacing later as an anonymous engine error.
"""

from __future__ import annotations

from .models import GameState, Response


class InvalidResponse(ValueError):
    """The bot's move is not a legal ``Response`` for this turn."""


def validate_response(response: object, state: GameState) -> Response:
    """Returns ``response`` unchanged if it is legal here, else raises.

    Raises:
        InvalidResponse: with a sentence that says what to do instead.
    """
    if not isinstance(response, Response):
        raise InvalidResponse(
            "act() must return a Response, but it returned "
            f"{type(response).__name__} ({response!r}). Use "
            "Response.fold(), Response.call(), Response.raise_to(total) "
            "or Response.all_in()."
        )
    legal = state.legal_actions
    kind = response.action_type
    if kind == "fold":
        if legal and "fold" not in legal:
            raise InvalidResponse(
                f"you cannot fold now; the legal moves are {', '.join(legal)}"
            )
        return response
    if kind == "call":
        if legal and "call" not in legal and "check" not in legal:
            raise InvalidResponse(
                "you cannot call or check now; the legal moves are "
                f"{', '.join(legal)}"
            )
        return response
    can_raise = "bet" in legal or "raise_to" in legal
    if legal and not can_raise:
        raise InvalidResponse(
            "you cannot bet or raise now (the legal moves are "
            f"{', '.join(legal)}); use Response.call() or Response.fold()"
        )
    if kind == "raise":
        low, high = state.min_raise_to, state.max_raise_to
        amount = response.amount
        if low is not None and high is not None and not low <= amount <= high:
            raise InvalidResponse(
                f"raise_to({amount}) is outside the allowed range: the total "
                f"must be between {low} and {high} chips"
            )
    return response
