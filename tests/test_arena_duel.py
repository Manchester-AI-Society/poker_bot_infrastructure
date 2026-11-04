"""Duplicate pairings: symmetry, determinism and scoring."""

from __future__ import annotations

import math

from arena.agents import LocalAgent
from arena.baselines import CallBot, FoldBot, RandomBot, ShoveBot
from arena.contestant import Contestant
from arena.duel import PairingConfig, deal_seed, play_pairing
from arena.stats import ci95, mean_and_se, t95


def contestant(name, bot_factory, **kwargs):
    return Contestant(
        name=name, factory=lambda: LocalAgent(bot_factory), **kwargs
    )


def test_identical_deterministic_strategies_score_exactly_zero():
    result = play_pairing(
        contestant("a", CallBot),
        contestant("b", CallBot),
        PairingConfig(deals=40, seed=5),
    )
    assert result.status == "complete"
    assert result.mean_bb == 0
    assert result.se_bb == 0
    assert result.hands_played == 80


def test_folding_every_hand_costs_exactly_three_quarters_of_a_big_blind():
    # Folding as the small blind loses 0.5 bb; as the big blind facing
    # a limp it forfeits 1 bb. Duplicate play averages both positions.
    result = play_pairing(
        contestant("folder", FoldBot),
        contestant("caller", CallBot),
        PairingConfig(deals=30, seed=1),
    )
    assert result.mean_bb == -0.75
    assert result.se_bb == 0


def test_scores_are_antisymmetric_when_the_bots_swap_sides():
    config = PairingConfig(deals=60, seed=9)

    def run(first, second):
        return play_pairing(
            contestant("x", first), contestant("y", second), config
        )

    forward = run(lambda: RandomBot(1), ShoveBot)
    backward = run(ShoveBot, lambda: RandomBot(1))
    assert math.isclose(forward.mean_bb, -backward.mean_bb, abs_tol=1e-9)


def test_same_seed_is_reproducible_and_different_seeds_are_not():
    def run(seed):
        return play_pairing(
            contestant("a", lambda: RandomBot(3)),
            contestant("b", ShoveBot),
            PairingConfig(deals=40, seed=seed),
        ).mean_bb

    assert run(11) == run(11)
    assert run(11) != run(12)


def test_hand_sink_receives_both_orientations_of_every_deal():
    seen = []
    play_pairing(
        contestant("a", CallBot),
        contestant("b", ShoveBot),
        PairingConfig(deals=6, seed=2),
        hand_sink=seen.append,
    )
    assert len(seen) == 12
    by_deal = {}
    for hand in seen:
        by_deal.setdefault(hand["deal"], []).append(hand)
    for deal, pair in by_deal.items():
        first, second = sorted(pair, key=lambda h: h["orientation"])
        # Same cards on the same seats, bots swapped between the seats.
        assert first["hole_cards"] == second["hole_cards"]
        assert first["board"] == second["board"]
        assert first["seats"] == ["a", "b"]
        assert second["seats"] == ["b", "a"]


def test_a_pairing_that_hits_the_time_cap_is_marked_incomplete():
    result = play_pairing(
        contestant("a", CallBot),
        contestant("b", CallBot),
        PairingConfig(deals=50, seed=1, time_cap_seconds=-1),
    )
    assert result.status == "incomplete"
    assert result.deals_completed == 0
    assert result.mean_bb is None


def test_deal_seeds_are_stable_and_distinct():
    assert deal_seed(1, 0) == deal_seed(1, 0)
    assert len({deal_seed(1, d) for d in range(1000)}) == 1000


def test_mean_and_se_basics():
    assert mean_and_se([]) == (None, float("inf"))
    assert mean_and_se([3.0]) == (3.0, float("inf"))
    mean, se = mean_and_se([1.0, 2.0, 3.0, 4.0])
    assert mean == 2.5
    assert math.isclose(se, math.sqrt(5 / 3 / 4))


def test_confidence_interval_uses_student_t_for_small_samples():
    assert t95(1) == 12.706
    assert t95(100) == 1.96
    assert ci95(0.5, 10) == t95(9) * 0.5
