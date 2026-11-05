"""The example bots in bots/ must actually work, not just exist."""

from __future__ import annotations

import importlib.util
import random
from pathlib import Path

import pytest

from arena.duel import PairingConfig, play_pairing
from arena.specs import contestant_from_spec
from arena.validate import smoke_test
from game.poker_hand_evaluator import evaluate_best_hand
from player_sdk.models import ActionRecord, GameState

REPO = Path(__file__).resolve().parents[1]
BOTS = REPO / "bots"
EXAMPLES = sorted(
    folder.name for folder in BOTS.iterdir() if (folder / "bot.py").is_file()
)


def load(name: str):
    spec = importlib.util.spec_from_file_location(
        f"example_{name}", BOTS / name / "bot.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_examples_are_there():
    assert {
        "starter",
        "tight_aggressive",
        "loose_aggressive",
        "the_rock",
        "equity_calc",
        "adaptive",
        "push_fold",
    } <= set(EXAMPLES)


@pytest.mark.parametrize("name", EXAMPLES)
def test_every_example_loads_and_plays_legally(name, tmp_path):
    report = smoke_test(BOTS / name, deals=10, log_dir=tmp_path)

    assert report.ok, report.message


@pytest.mark.parametrize("name", EXAMPLES)
def test_every_example_has_a_docstring_saying_how_to_try_it(name):
    text = (BOTS / name / "bot.py").read_text(encoding="utf-8")

    assert text.lstrip().startswith('"""')
    assert "python -m arena match" in text


@pytest.mark.parametrize("name", EXAMPLES)
def test_every_example_beats_a_random_player(name):
    config = PairingConfig(deals=100, seed=5, think_budget_per_deal=2.0)

    result = play_pairing(
        contestant_from_spec(str(BOTS / name)),
        contestant_from_spec("random"),
        config,
    )

    assert result.status == "complete"
    assert result.faults_a == 0
    assert result.mean_bb > 0


@pytest.mark.parametrize("name", EXAMPLES)
def test_examples_are_self_contained(name):
    # A team's folder is all that gets copied, so a bot may not import a
    # sibling bot or the repo's own game code.
    text = (BOTS / name / "bot.py").read_text(encoding="utf-8")

    for line in text.splitlines():
        if line.startswith(("import ", "from ")):
            assert not line.startswith(
                ("from bots", "import bots", "from game")
            ), line
            assert "arena" not in line, line


# -- the equity bot's own hand evaluator ------------------------------


@pytest.fixture(scope="module")
def equity():
    return load("equity_calc")


def value(equity, cards: str):
    return equity.hand_value(equity.parse(cards.split()))


@pytest.mark.parametrize(
    "better, worse",
    [
        (
            "9S 8S 7S 6S 5S 2D 3D",
            "AS AD AC AH KS 2D 3D",
        ),  # straight flush > quads
        ("AS AD AC AH 2S 3D 4D", "AS AD AC KH KS 3D 4D"),  # quads > full house
        ("AS AD AC KH KS 3D 4D", "AS KS 9S 5S 2S 3D 4D"),  # full house > flush
        ("AS KS 9S 5S 2S 3D 4D", "AS 2D 3C 4H 5S KD 9C"),  # flush > straight
        ("2D 3C 4H 5S 6S KD 9C", "AS 2D 3C 4H 5S KD 9C"),  # 6-high > wheel
        (
            "AS KD QC JH TS 2D 3D",
            "AS AD KC KH QS 3D 9D",
        ),  # broadway > two pair
        ("9S 9D 9C KH 2S 3D 4D", "AS AD KC KH 2S 3D 4D"),  # trips > two pair
        ("AS AD KC KH 2S 3D 4D", "AS AD QC QH 2S 3D 4D"),  # AAKK > AAQQ
        ("AS AD KC 5H 2S 3D 9D", "AS AD QC 5H 2S 3D 9D"),  # kicker decides
        ("AS KD 9C 5H 2S 3D 7D", "AS QD 9C 5H 2S 3D 7D"),  # high card kicker
    ],
)
def test_evaluator_orders_hands_correctly(equity, better, worse):
    assert value(equity, better) > value(equity, worse)


def test_wheel_is_a_five_high_straight_not_an_ace_high_one(equity):
    wheel = value(equity, "AS 2D 3C 4H 5S KD 9C")

    assert wheel == (4, 5)


def test_three_pairs_use_the_best_two_and_the_best_kicker(equity):
    # AA KK QQ + 2: the third pair's queen is the kicker.
    assert value(equity, "AS AD KC KH QS QD 2D") == (2, 14, 13, 12)


def test_two_sets_make_a_full_house_with_the_higher_first(equity):
    assert value(equity, "AS AD AC KH KS KD 2D") == (6, 14, 13)


def test_a_flush_beats_trips_and_pairs_that_do_not_make_a_house(equity):
    # Five spades plus three twos is a flush with trips on the side (no pair
    # to go with the trips, so no full house); the flush is the better hand.
    assert value(equity, "AS KS 9S 5S 2S 2D 2C")[0] == 5
    assert value(equity, "AS KS 9S 5S 2S 3D 3C")[0] == 5
    # Add a pair to those trips and it becomes a full house, which wins.
    assert value(equity, "AS KS 9S 2S 2D 2C 9D")[0] == 6


def test_evaluator_agrees_with_the_engine_on_random_showdowns(equity):
    rng = random.Random(1)
    for _ in range(3000):
        cards = rng.sample(equity.FULL_DECK, 9)
        board, first, second = cards[:5], cards[5:7], cards[7:9]
        mine = (
            equity.hand_value(equity.parse(first + board))
            > equity.hand_value(equity.parse(second + board)),
            equity.hand_value(equity.parse(first + board))
            < equity.hand_value(equity.parse(second + board)),
        )
        engine_first = evaluate_best_hand(first + board)[0]
        engine_second = evaluate_best_hand(second + board)[0]
        theirs = engine_first > engine_second, engine_first < engine_second
        assert mine == theirs, (first, second, board)


def test_equity_is_sensible(equity):
    bot = equity.EquityBot()

    aces = bot.equity(["AS", "AD"], [])
    trash = bot.equity(["7C", "2D"], [])
    nuts = bot.equity(["AS", "KS"], ["QS", "JS", "TS"])  # a royal flush

    assert aces > 0.75 > 0.40 > trash
    assert nuts == 1.0


# -- the adaptive bot's learning --------------------------------------


def state(adaptive, history, hole=("AS", "KS")):
    return GameState(
        hole_cards=hole,
        community_cards=(),
        pot_size=30,
        stack_sizes=(2000, 2000),
        current_bets=(10, 20),
        current_player_index=0,
        call_amount=10,
        minimum_raise=20,
        action_history=tuple(history),
        legal_actions=("fold", "call", "raise_to"),
        my_index=0,
        street="preflop",
        player_ids=("seat0", "seat1"),
        min_raise_to=40,
        max_raise_to=2000,
        dealer_index=0,
        small_blind=10,
        big_blind=20,
    )


def hand_where_opponent_folds(i):
    return [
        ActionRecord("seat0", "post_small_blind", 10, "preflop"),
        ActionRecord("seat1", "post_big_blind", 20, "preflop"),
        ActionRecord("seat0", "raise_to", 60, "preflop"),
        ActionRecord("seat1", "fold", None, "preflop"),
    ]


def test_adaptive_learns_that_an_opponent_folds_to_bets():
    adaptive = load("adaptive").AdaptiveBot()
    assert adaptive.fold_rate == 0.40  # the prior, before enough evidence

    for i in range(15):
        hole = ("AS", "KS") if i % 2 else ("2C", "7D")  # a new hand each time
        adaptive._learn(state(adaptive, hand_where_opponent_folds(i), hole))

    assert adaptive.faced == 15 and adaptive.folded == 15
    assert adaptive.fold_rate == 1.0


def test_adaptive_does_not_count_the_same_actions_twice_within_a_hand():
    adaptive = load("adaptive").AdaptiveBot()
    history = hand_where_opponent_folds(0)

    for _ in range(5):  # asked to act repeatedly with the same history
        adaptive._learn(state(adaptive, history))

    assert adaptive.faced == 1


def test_adaptive_counts_aggression_and_ignores_its_own_moves():
    adaptive = load("adaptive").AdaptiveBot()
    history = [
        ActionRecord("seat0", "post_small_blind", 10, "preflop"),
        ActionRecord("seat1", "post_big_blind", 20, "preflop"),
        ActionRecord("seat0", "call", 10, "preflop"),
        ActionRecord("seat1", "raise_to", 60, "preflop"),
    ]

    adaptive._learn(state(adaptive, history))

    assert adaptive.aggressive == 1
    assert adaptive.passive == 0  # our own call is not the opponent's
