"""Bot failure handling with real child processes."""

from __future__ import annotations

import textwrap

import pytest

from arena.agents import AgentCrashed, LocalAgent, ProcessAgent
from arena.baselines import CallBot
from arena.contestant import Contestant
from arena.duel import PairingConfig, play_pairing

HEADER = """
from player_sdk.bot_interface import PokerBot
from player_sdk.models import Action
"""


def write_bot(tmp_path, name, body):
    path = tmp_path / f"{name}.py"
    path.write_text(HEADER + textwrap.dedent(body))
    return path


def process_contestant(path, tmp_path, **kwargs):
    kwargs.setdefault("move_timeout", 5.0)
    return Contestant(
        name=path.stem,
        factory=lambda: ProcessAgent(
            path, log_path=tmp_path / f"{path.stem}.log", startup_timeout=30
        ),
        **kwargs,
    )


def caller():
    return Contestant(name="caller", factory=lambda: LocalAgent(CallBot))


def run(contestant, deals=4):
    return play_pairing(
        contestant,
        caller(),
        PairingConfig(deals=deals, seed=1, think_budget_per_deal=60),
    )


def test_a_well_behaved_bot_runs_without_faults(tmp_path):
    path = write_bot(
        tmp_path,
        "good",
        """
        class Good(PokerBot):
            def act(self, game_state):
                return Action.call()
        """,
    )
    result = run(process_contestant(path, tmp_path))
    assert result.status == "complete"
    assert result.faults_a == 0
    assert result.disabled_a is None
    assert result.mean_bb == 0  # call vs call is symmetric


def test_prints_go_to_the_private_log_not_the_protocol(tmp_path):
    path = write_bot(
        tmp_path,
        "chatty",
        """
        class Chatty(PokerBot):
            def act(self, game_state):
                print("thinking about", game_state.hole_cards)
                return Action.call()
        """,
    )
    result = run(process_contestant(path, tmp_path))
    assert result.faults_a == 0
    log = (tmp_path / "chatty.log").read_text()
    assert "thinking about" in log


def test_an_exception_costs_a_fault_and_play_continues(tmp_path):
    path = write_bot(
        tmp_path,
        "buggy",
        """
        class Buggy(PokerBot):
            def act(self, game_state):
                raise RuntimeError("boom")
        """,
    )
    result = run(process_contestant(path, tmp_path, max_faults=1000))
    assert result.status == "complete"
    assert result.faults_a > 0
    assert any("boom" in line for line in result.fault_log_a)
    assert result.disabled_a is None


def test_too_many_faults_replace_the_bot_with_an_always_fold_stub(tmp_path):
    path = write_bot(
        tmp_path,
        "broken",
        """
        class Broken(PokerBot):
            def act(self, game_state):
                raise RuntimeError("boom")
        """,
    )
    result = run(process_contestant(path, tmp_path, max_faults=3), deals=10)
    assert result.faults_a == 3
    assert "3 faults" in result.disabled_a
    # Once disabled the bot folds, which loses chips against a caller.
    assert result.mean_bb < 0


def test_a_hanging_bot_is_killed_and_timed_out(tmp_path):
    path = write_bot(
        tmp_path,
        "slow",
        """
        import time

        class Slow(PokerBot):
            def act(self, game_state):
                time.sleep(30)
                return Action.call()
        """,
    )
    contestant = process_contestant(
        path, tmp_path, move_timeout=0.4, max_faults=2
    )
    result = run(contestant, deals=2)
    assert result.faults_a == 2
    assert any("AgentTimeout" in line for line in result.fault_log_a)
    assert result.disabled_a is not None


def test_a_bot_that_exits_is_restarted_and_counted(tmp_path):
    path = write_bot(
        tmp_path,
        "quitter",
        """
        import sys

        class Quitter(PokerBot):
            def act(self, game_state):
                sys.exit(3)
        """,
    )
    result = run(process_contestant(path, tmp_path, max_faults=4), deals=3)
    assert result.faults_a == 4
    assert any("AgentCrashed" in line for line in result.fault_log_a)


def test_an_illegal_move_is_a_fault_and_replaced_by_a_legal_one(tmp_path):
    path = write_bot(
        tmp_path,
        "cheeky",
        """
        class Cheeky(PokerBot):
            def act(self, game_state):
                return Action.raise_to(1)  # below any legal raise
        """,
    )
    result = run(process_contestant(path, tmp_path, max_faults=1000))
    assert result.status == "complete"
    assert result.faults_a > 0
    assert any("allowed range" in line for line in result.fault_log_a)


def test_returning_the_wrong_type_is_a_fault(tmp_path):
    path = write_bot(
        tmp_path,
        "wrongtype",
        """
        class WrongType(PokerBot):
            def act(self, game_state):
                return "call"
        """,
    )
    result = run(process_contestant(path, tmp_path, max_faults=1000))
    assert result.faults_a > 0
    assert any("must return a Response" in line for line in result.fault_log_a)


def test_a_bot_that_cannot_be_imported_is_disabled_immediately(tmp_path):
    path = write_bot(
        tmp_path,
        "badimport",
        """
        import module_that_does_not_exist

        class Bad(PokerBot):
            def act(self, game_state):
                return Action.call()
        """,
    )
    result = run(process_contestant(path, tmp_path), deals=2)
    assert result.disabled_a == "bot failed to start"
    assert any(
        "module_that_does_not_exist" in line for line in result.fault_log_a
    )


def test_two_pokerbot_subclasses_is_a_load_error(tmp_path):
    path = write_bot(
        tmp_path,
        "twins",
        """
        class A(PokerBot):
            def act(self, game_state):
                return Action.call()

        class B(PokerBot):
            def act(self, game_state):
                return Action.call()
        """,
    )
    with pytest.raises(AgentCrashed, match="exactly one PokerBot"):
        ProcessAgent(path, startup_timeout=30)


def test_closing_an_agent_twice_is_safe(tmp_path):
    path = write_bot(
        tmp_path,
        "closer",
        """
        class Closer(PokerBot):
            def act(self, game_state):
                return Action.call()
        """,
    )
    agent = ProcessAgent(path, startup_timeout=30)
    agent.close()
    agent.close()  # must not raise


def test_a_teardown_timeout_does_not_raise(tmp_path, monkeypatch):
    import subprocess

    path = write_bot(
        tmp_path,
        "stubborn",
        """
        class Stubborn(PokerBot):
            def act(self, game_state):
                return Action.call()
        """,
    )
    agent = ProcessAgent(path, startup_timeout=30)
    real_wait = agent._proc.wait

    def slow_wait(timeout=None):
        if timeout in (0.3, 10):
            raise subprocess.TimeoutExpired("bot", timeout)
        return real_wait(timeout)

    monkeypatch.setattr(agent._proc, "wait", slow_wait)
    agent.close()  # kill path with a wait that times out: no exception
    real_wait(10)
