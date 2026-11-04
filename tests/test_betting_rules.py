"""Betting-round rules: all-ins, minimum raises and hand run-outs."""

from __future__ import annotations

import asyncio

import pytest

from game.game_domain_models import InvalidActionError

from .engine_helpers import act, new_match, rig, stacks


def test_short_all_in_raise_does_not_lower_the_minimum_raise():
    async def scenario():
        # p0 button, p1 small blind, p2 big blind with only 70 chips.
        service, runtime = await new_match([1000, 1000, 70])
        await act(service, runtime, "raise_to", 60)  # full raise (+40)
        await act(service, runtime, "fold")  # p1
        await act(service, runtime, "raise_to", 70)  # p2 shoves: only +10
        return service.get_public_state(runtime.match_id, "p0")

    state = asyncio.run(scenario())
    # The raise increment stays 40: 70 + 40 = 110, not 70 + 20.
    assert state["min_raise_to"] == 110


def test_non_all_in_raise_below_minimum_is_still_rejected():
    async def scenario():
        service, runtime = await new_match([1000, 1000])
        await act(service, runtime, "raise_to", 30)

    with pytest.raises(InvalidActionError):
        asyncio.run(scenario())


def test_short_stack_may_bet_less_than_a_big_blind_all_in():
    async def scenario():
        service, runtime = await new_match([1000, 1000, 35])
        await act(service, runtime, "call")  # p0
        await act(service, runtime, "call")  # p1
        await act(service, runtime, "check")  # p2 (15 chips left)
        await act(service, runtime, "check")  # flop: p1
        await act(service, runtime, "bet", 15)  # p2 bets 15 < big blind
        return runtime

    runtime = asyncio.run(scenario())
    assert runtime.players[2].curr_balance == 0
    assert runtime.status == "running"


def test_heads_up_shove_and_call_runs_the_board_out():
    async def scenario():
        service, runtime = await new_match([500, 500])
        rig(runtime, {0: "AS AD", 1: "KS KD"}, "2C 7D 9H JC 3S")
        await act(service, runtime, "raise_to", 500)  # SB shoves
        await act(service, runtime, "call")  # BB calls
        return runtime

    runtime = asyncio.run(scenario())
    assert runtime.status == "finished"
    assert runtime.engine.board.revealed_cards == 5
    assert stacks(runtime) == [1000, 0]


def test_heads_up_shove_and_fold_awards_the_pot_to_the_shover():
    async def scenario():
        service, runtime = await new_match([500, 500])
        await act(service, runtime, "raise_to", 500)
        await act(service, runtime, "fold")
        return runtime

    runtime = asyncio.run(scenario())
    assert runtime.status == "finished"
    assert stacks(runtime) == [520, 480]


def test_lone_player_facing_a_short_all_in_is_not_prompted_again():
    async def scenario():
        service, runtime = await new_match([1000, 100])
        rig(runtime, {0: "AS AD", 1: "KS KD"}, "2C 7D 9H JC 3S")
        await act(service, runtime, "raise_to", 300)  # SB raises
        await act(service, runtime, "call")  # BB calls all-in for 100
        return runtime

    runtime = asyncio.run(scenario())
    # p0's unmatched 200 is returned; nothing else to decide.
    assert runtime.status == "finished"
    assert stacks(runtime) == [1100, 0]
