"""Local runner: CLI, hand history files and the starter bot."""

from __future__ import annotations

from pathlib import Path

from arena.cli import main
from arena.history import read_hands
from arena.validate import smoke_test
from bots.starter.bot import (
    StarterBot,
    postflop_strength,
    preflop_strength,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
STARTER = REPO_ROOT / "bots" / "starter"


def test_starter_bot_passes_validation(tmp_path):
    report = smoke_test(STARTER, deals=10, log_dir=tmp_path)
    assert report.ok, report.message


def test_validation_reports_a_broken_bot(tmp_path):
    bot = tmp_path / "bot.py"
    bot.write_text(
        "from player_sdk.bot_interface import PokerBot\n"
        "class B(PokerBot):\n"
        "    def act(self, s):\n"
        "        raise ValueError('nope')\n"
    )
    report = smoke_test(bot, deals=5, log_dir=tmp_path)
    assert not report.ok
    assert "nope" in report.message


def test_match_command_writes_replayable_hand_histories(tmp_path, capsys):
    hands = tmp_path / "hands.jsonl.gz"
    code = main(
        [
            "match",
            str(STARTER),
            "@fold",
            "--deals",
            "15",
            "--hands",
            str(hands),
            "--log-dir",
            str(tmp_path / "logs"),
        ]
    )
    out = capsys.readouterr().out
    assert code == 0
    assert "starter" in out and "95% CI" in out
    records = list(read_hands(hands))
    assert len(records) == 30
    first = records[0]
    assert {"hole_cards", "board", "actions", "net", "deal_seed"} <= set(first)
    assert sum(first["net"]) == 0


def test_same_bot_on_both_sides_gets_distinct_names(tmp_path, capsys):
    code = main(
        [
            "match",
            "@call",
            "@call",
            "--deals",
            "5",
            "--log-dir",
            str(tmp_path),
        ]
    )
    assert code == 0
    assert "@call-1" in capsys.readouterr().out


def test_starter_hand_strength_orders_hands_sensibly():
    assert preflop_strength(["AS", "AD"]) > preflop_strength(["KS", "QD"])
    assert preflop_strength(["KS", "QS"]) > preflop_strength(["KS", "QD"])
    assert preflop_strength(["7S", "2D"]) < 0.3
    flush = postflop_strength(["AS", "2S"], ["5S", "9S", "KS"])
    pair = postflop_strength(["AS", "2D"], ["AH", "9C", "4S"])
    nothing = postflop_strength(["AS", "2D"], ["KH", "9C", "4S"])
    assert flush > pair > nothing


def test_starter_never_returns_an_illegal_raise_size():
    """Exercise the sizing helper over the whole legal range."""
    from player_sdk.models import GameState

    for low, high, pot, bet in [(40, 2000, 30, 20), (2000, 600, 90, 0)]:
        state = GameState(
            hole_cards=("AS", "AD"),
            community_cards=(),
            pot_size=pot,
            stack_sizes=(2000, 2000),
            current_bets=(bet, 0),
            current_player_index=0,
            call_amount=0,
            minimum_raise=low,
            action_history=(),
            my_index=0,
            min_raise_to=low,
            max_raise_to=high,
            legal_actions=("fold", "check", "raise_to"),
        )
        action = StarterBot().act(state)
        assert action.amount is not None
        assert min(low, high) <= action.amount <= high


def test_baselines_work_without_the_at_sign(tmp_path, capsys):
    # PowerShell treats a leading @ as its splat operator and silently drops
    # the argument, so `match bots/starter @call` fails there.
    code = main(
        [
            "match",
            "bots/starter",
            "call",
            "--deals",
            "5",
            "--log-dir",
            str(tmp_path),
        ]
    )

    assert code == 0
    assert "@call" in capsys.readouterr().out


def test_a_real_bot_folder_wins_over_a_baseline_of_the_same_name(
    tmp_path, monkeypatch
):
    from arena.specs import contestant_from_spec

    folder = tmp_path / "call"
    folder.mkdir()
    (folder / "bot.py").write_text("# not a baseline\n")
    monkeypatch.chdir(tmp_path)

    contestant = contestant_from_spec("call")

    assert contestant.name == "call"  # the folder, not the @call baseline
    assert contestant.factory.__name__ == "<lambda>"  # a child-process bot


def test_an_unknown_name_still_reports_a_missing_bot():
    import pytest

    from arena.specs import contestant_from_spec

    with pytest.raises(FileNotFoundError, match="nonexistent"):
        contestant_from_spec("nonexistent")
