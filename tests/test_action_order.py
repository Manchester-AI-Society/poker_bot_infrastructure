"""Who acts first on each street."""

from __future__ import annotations

import asyncio

from .engine_helpers import act, new_match


async def _streets_first_actors(stacks):
    """Checks/calls around the table; returns the first actor per street."""
    service, runtime = await new_match(stacks, max_hands=2)
    seen = {}
    while runtime.status == "running" and len(seen) < 4:
        state = service.get_public_state(runtime.match_id)
        actor = state["current_player_id"]
        seen.setdefault(state["street"], actor)
        view = service.get_public_state(runtime.match_id, actor)
        await act(
            service,
            runtime,
            "check" if "check" in view["legal_actions"] else "call",
        )
    return seen


def test_heads_up_big_blind_acts_first_after_the_flop():
    seen = asyncio.run(_streets_first_actors([1000, 1000]))
    # Button (p0) is the small blind and acts first preflop only.
    assert seen == {
        "preflop": "p0",
        "flop": "p1",
        "turn": "p1",
        "river": "p1",
    }


def test_multiway_small_blind_acts_first_after_the_flop():
    seen = asyncio.run(_streets_first_actors([1000, 1000, 1000]))
    # p0 button, p1 small blind, p2 big blind; preflop starts at p0.
    assert seen == {
        "preflop": "p0",
        "flop": "p1",
        "turn": "p1",
        "river": "p1",
    }
