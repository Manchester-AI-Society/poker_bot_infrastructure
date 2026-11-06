"""The public event log carries what a spectator needs to replay a hand."""

from __future__ import annotations

import asyncio

from game.game_domain_models import InvalidActionError
from game.game_service_core import GameService
from tests.engine_helpers import act, new_match, rig


def events_of(runtime, kind):
    return [e for e in runtime.action_log if e["type"] == kind]


def play_to_fold(stacks=(1000, 1000)):
    async def scenario():
        service, runtime = await new_match(list(stacks), max_hands=1)
        await act(service, runtime, "raise_to", 60)
        await act(service, runtime, "fold")
        return runtime

    return asyncio.run(scenario())


def play_to_showdown():
    async def scenario():
        service, runtime = await new_match([1000, 1000], max_hands=1)
        rig(runtime, {0: "AS AH", 1: "7C 2D"}, "KD 9S 4H 3C JD")
        # Everybody calls or checks it down.
        for _ in range(12):
            if events_of(runtime, "showdown"):
                break
            try:
                await act(service, runtime, "check")
            except InvalidActionError:
                await act(service, runtime, "call")
        return runtime

    return asyncio.run(scenario())


# -- the start of a hand ------------------


def test_a_hand_start_lists_the_seats_stacks_and_blinds():
    runtime = play_to_fold()
    (start,) = events_of(runtime, "hand_started")
    assert start["players"] == ["p0", "p1"]
    # Stacks are what each seat had BEFORE the blinds went in.
    assert start["stacks"] == {"p0": 1000, "p1": 1000}
    assert sorted(b["amount"] for b in start["blinds"]) == [10, 20]
    assert {b["player_id"] for b in start["blinds"]} == {"p0", "p1"}


def test_stacks_at_the_start_of_a_later_hand_include_earlier_winnings():
    async def scenario():
        service, runtime = await new_match([1000, 1000], max_hands=2)
        await act(service, runtime, "raise_to", 60)
        await act(service, runtime, "fold")
        return runtime

    runtime = asyncio.run(scenario())
    starts = events_of(runtime, "hand_started")
    assert len(starts) == 2
    after = events_of(runtime, "showdown")[0]["stacks"]
    assert starts[1]["stacks"] == after  # next hand starts from the payout
    assert sum(after.values()) == 2000  # no chips created or lost


# -- actions ------------------


def test_each_action_carries_the_stack_and_bet_after_it():
    runtime = play_to_fold()
    first, second = events_of(runtime, "action")[:2]
    assert first["action"] == "raise_to" or first["action"] == "bet"
    assert first["stack"] + first["bet"] == 1000  # chips are only moved
    assert second["action"] == "fold" and "stack" in second and "bet" in second


# -- the end of a hand ------------------


def test_a_fold_never_reveals_anyones_cards():
    runtime = play_to_fold()
    (end,) = events_of(runtime, "showdown")
    assert "hole_cards" not in end and "board" not in end
    assert sum(end["stacks"].values()) == 2000
    assert {r["hand"] for r in end["results"]} == {"Won by Fold", "Folded"}


def test_a_showdown_shows_only_the_hands_that_reached_it():
    runtime = play_to_showdown()
    (end,) = events_of(runtime, "showdown")
    assert end["hole_cards"] == {"p0": ["AS", "AH"], "p1": ["7C", "2D"]}
    assert end["board"] == ["KD", "9S", "4H", "3C", "JD"]
    assert sum(end["stacks"].values()) == 2000
    winner = max(end["results"], key=lambda r: r["winnings"])
    assert winner["player_id"] == "p0"


# -- the log is not allowed to lose events ------------------


def test_tournament_tables_keep_a_very_long_event_log():
    service = GameService()
    runtime = service.create_match(
        player_ids=["a", "b"],
        starting_stack=100,
        small_blind=1,
        big_blind=2,
        turn_timeout_seconds=60,
        wait_for_players=False,
        event_log_limit=100_000,
    )
    assert runtime.action_log.maxlen == 100_000
