"""Hand-level tests of the arena table, including a rules fuzz."""

from __future__ import annotations

import random

from arena.agents import LocalAgent
from arena.baselines import CallBot, FoldBot, RandomBot, ShoveBot
from arena.contestant import Contestant
from arena.table import play_hand


def contestant(name, bot_factory, **kwargs):
    return Contestant(
        name=name, factory=lambda: LocalAgent(bot_factory), **kwargs
    )


def test_fold_bot_loses_its_blind_heads_up():
    folder = contestant("fold", FoldBot)
    caller = contestant("call", CallBot)
    record = play_hand(
        [folder, caller], deal_seed=1, stacks=[2000, 2000], big_blind=20
    )
    # Seat 0 is the button/small blind and folds: loses 10.
    assert record.net == [-10, 10]
    assert record.ended_by == "fold"


def test_same_seed_replays_the_same_hand():
    def run():
        a = contestant("a", CallBot)
        b = contestant("b", CallBot)
        return play_hand([a, b], deal_seed=42, stacks=[2000, 2000])

    first, second = run(), run()
    assert first.hole_cards == second.hole_cards
    assert first.board == second.board
    assert first.net == second.net


def test_record_has_everything_needed_to_replay():
    a = contestant("a", CallBot)
    b = contestant("b", ShoveBot)
    record = play_hand([a, b], deal_seed=3, stacks=[2000, 2000])
    data = record.to_dict()
    assert len(data["hole_cards"]) == 2 and len(data["board"]) == 5
    assert data["actions"][0]["action"] == "post_small_blind"
    assert data["actions"][1]["action"] == "post_big_blind"
    assert data["net"] == record.net and sum(data["net"]) == 0


def test_shove_bot_vs_call_bot_always_resolves_heads_up():
    for seed in range(60):
        a = contestant("shove", ShoveBot)
        b = contestant("call", CallBot)
        record = play_hand([a, b], deal_seed=seed, stacks=[2000, 2000])
        assert sum(record.net) == 0
        assert abs(record.net[0]) in (0, 20, 10, 2000)


def test_fuzz_random_bots_conserve_chips_and_never_fault():
    """Random legal play over uneven stacks: no crashes, no illegal
    moves, chips always conserved (asserted inside play_hand)."""
    rng = random.Random(2024)
    for index in range(1500):
        stacks = [rng.randint(1, 3000), rng.randint(1, 3000)]
        a = contestant("a", lambda s=index: RandomBot(s))
        b = contestant("b", lambda s=index + 1: RandomBot(s))
        record = play_hand(
            [a, b],
            deal_seed=index,
            hand_index=index,
            stacks=stacks,
        )
        assert record.faults == 0, record.actions
        assert sum(record.net) == 0
        # No one can win or lose more than the smaller stack.
        assert max(abs(n) for n in record.net) <= min(stacks)


def test_fuzz_three_handed_with_side_pots():
    rng = random.Random(7)
    for index in range(800):
        stacks = [rng.randint(20, 2000) for _ in range(3)]
        seats = [
            contestant(f"s{i}", lambda s=index * 3 + i: RandomBot(s))
            for i in range(3)
        ]
        record = play_hand(
            seats,
            deal_seed=index,
            stacks=stacks,
        )
        assert record.faults == 0, record.actions
        assert sum(record.net) == 0
        for seat, net in enumerate(record.net):
            assert net >= -stacks[seat]
