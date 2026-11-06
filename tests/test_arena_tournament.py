"""The two-round tournament, played with real bot processes."""

from __future__ import annotations

import time

import pytest

from arena import leaderboard
from arena.intake import submit
from arena.store import Store
from arena.tournament import (
    Runner,
    TournamentError,
    TournamentSettings,
    balanced_sizes,
    draw,
    draw_groups,
    qualifiers,
    remove_team,
    revealed,
    settle,
    start_finals,
    start_groups,
    state_of,
    status,
    team_names,
)

HEADER = (
    "from player_sdk.bot_interface import PokerBot\n"
    "from player_sdk.models import Response\n"
)
BODIES = {
    "call": "class B(PokerBot):\n    def act(self, s):\n"
    "        return Response.call()\n",
    "fold": "class B(PokerBot):\n    def act(self, s):\n"
    "        return Response.fold()\n",
    "shove": "class B(PokerBot):\n    def act(self, s):\n"
    "        return Response.all_in()\n",
}

# -- the draw -------------------


@pytest.mark.parametrize(
    "count, largest, expected",
    [
        (20, 8, [7, 7, 6]),
        (17, 8, [6, 6, 5]),
        (16, 8, [8, 8]),
        (8, 8, [8]),
        (9, 8, [5, 4]),
        (2, 8, [2]),
        (25, 8, [7, 6, 6, 6]),
    ],
)
def test_groups_are_as_even_as_possible_and_never_too_big(
    count, largest, expected
):
    sizes = balanced_sizes(count, largest)
    assert sizes == expected
    assert sum(sizes) == count and max(sizes) <= largest
    assert max(sizes) - min(sizes) <= 1


def test_the_draw_places_everyone_once_and_is_reproducible():
    teams = [f"team{i:02d}" for i in range(20)]
    first = draw_groups(teams, 8, seed=42)
    again = draw_groups(list(reversed(teams)), 8, seed=42)
    assert first == again  # same seed, same draw, whatever the input order
    assert sorted(t for g in first for t in g) == sorted(teams)
    assert [len(g) for g in first] == [7, 7, 6]
    assert draw_groups(teams, 8, seed=43) != first


# -- teams from imported bots -------------------


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "data")


def add(store, tmp_path, team, kind="call"):
    """Imports a real bot for ``team`` (a comment keeps each hash unique)."""
    folder = tmp_path / "src" / team
    folder.mkdir(parents=True)
    (folder / "bot.py").write_text(
        HEADER + BODIES[kind] + f"# {team}\n", encoding="utf-8"
    )
    result = submit(store, team, str(folder), validate=False)
    assert result.accepted
    return result


def fake(store, team):
    """A team without a bot process, for tests that never play."""
    store.add_version(team, f"h-{team}", "", "valid", "")
    store.set_current(team, f"h-{team}")


def test_a_tournament_needs_teams_with_working_bots(store):
    with pytest.raises(TournamentError, match="import the submissions"):
        state_of(store)
    fake(store, "a")
    with pytest.raises(TournamentError, match="at least two teams"):
        draw(store)
    assert team_names(store) == ["a"]


def test_a_bot_that_failed_its_check_is_not_a_team(store, tmp_path):
    folder = tmp_path / "bad"
    folder.mkdir()
    (folder / "bot.py").write_text(
        HEADER + "class B(PokerBot):\n    def act(self, s):\n        raise 1\n"
    )
    assert submit(store, "bad", str(folder)).status == "invalid"
    fake(store, "good")
    assert team_names(store) == ["good"]


def test_the_draw_cannot_be_redone_silently(store):
    for t in "abcd":
        fake(store, t)
    draw(store, group_size=2, seed=1)
    with pytest.raises(TournamentError, match="redo"):
        draw(store, group_size=2, seed=2)
    again = draw(store, group_size=2, seed=2, redo=True)
    assert again["seed"] == 2 and again["phase"] == "drawn"


def test_phases_must_come_in_order(store):
    for t in "abcd":
        fake(store, t)
    with pytest.raises(TournamentError, match="import the submissions"):
        start_groups(store)
    draw(store, group_size=2, seed=1)
    with pytest.raises(TournamentError, match="finals start"):
        start_finals(store)
    assert start_groups(store, deals=2) == 2  # two groups of two: 1 + 1
    with pytest.raises(TournamentError, match="final once"):
        draw(store, redo=True)
    with pytest.raises(TournamentError, match="draw the groups first"):
        start_groups(store)


def test_a_team_can_be_removed_only_before_the_draw(store):
    for t in "abc":
        fake(store, t)
    remove_team(store, "b")
    assert team_names(store) == ["a", "c"]
    with pytest.raises(TournamentError, match="no team"):
        remove_team(store, "b")
    draw(store, group_size=8, seed=1)
    with pytest.raises(TournamentError, match="before the draw"):
        remove_team(store, "a")


def test_results_are_revealed_only_when_a_round_is_over():
    assert revealed(None) == {"groups": False, "finals": False}
    for phase, groups, finals in [
        ("registration", False, False),
        ("drawn", False, False),
        ("groups", False, False),
        ("between", True, False),
        ("finals", True, False),
        ("done", True, True),
    ]:
        assert revealed({"phase": phase}) == {
            "groups": groups,
            "finals": finals,
        }


# -- a whole tournament with real bots -------------------

BOTS = {
    "fox": "call",
    "owl": "fold",
    "bear": "shove",
    "wolf": "call",
    "mole": "fold",
    "hare": "shove",
}


def folders_apart():
    """A seed whose groups of three each hold exactly one folder."""
    for seed in range(1, 300):
        groups = draw_groups(sorted(BOTS), 3, seed)
        if all(sum(t in ("owl", "mole") for t in g) == 1 for g in groups):
            return seed
    raise AssertionError("no such seed")


def run_until(runner, store, phase, seconds=180):
    deadline = time.time() + seconds
    while store.tournament()["phase"] != phase:
        assert time.time() < deadline, f"stuck at {store.tournament()}"
        runner.step()
        time.sleep(0.05)


@pytest.fixture
def played(store, tmp_path):
    for team, kind in BOTS.items():
        add(store, tmp_path, team, kind)
    settings = TournamentSettings(concurrency=4, think_budget_per_deal=60)
    runner = Runner(store, settings, log=lambda m: None)
    yield store, runner
    runner.close()


def test_a_full_tournament_groups_then_finals(played):
    store, runner = played
    draw(store, group_size=3, advance=2, seed=folders_apart())

    assert start_groups(store, deals=3) == 6  # two groups of three: 3 + 3
    run_until(runner, store, "between")

    state = state_of(store)
    assert len(state["finalists"]) == 4
    # A folder loses to everyone, so neither folder reaches the final.
    assert "owl" not in state["finalists"] and "mole" not in state["finalists"]
    assert state["finalists"] == qualifiers(store, state)
    for group in state["groups"]:
        board = leaderboard.compute(store, "group", group["freeze"])
        assert board["pairs_done"] == board["pairs_total"] == 3
        assert board["teams"][-1]["team"] in ("owl", "mole")

    assert start_finals(store, deals=3) == 6  # four finalists: 6 pairings
    run_until(runner, store, "done")
    final = leaderboard.compute(
        store, "final", state_of(store)["finals_freeze"]
    )
    assert final["pairs_done"] == final["pairs_total"] == 6
    assert state_of(store)["champion"] == final["teams"][0]["team"]
    assert state_of(store)["champion"] in state["finalists"]
    # Every match left a hand history behind.
    assert len(list((store.root / "hands").glob("*.jsonl.gz"))) == 12


def test_a_match_left_running_by_a_dead_run_is_replayed_on_restart(
    store, tmp_path
):
    for team, kind in BOTS.items():
        add(store, tmp_path, team, kind)
    draw(store, group_size=8, seed=1)
    start_groups(store, deals=2)
    job = store.jobs_of("group")[0]
    # A previous `tournament run` died while this match was running.
    assert store.claim_job_by_id(job["id"], "scheduler-2147483000")
    assert store.jobs_of("group")[0]["status"] == "running"

    runner = Runner(
        store,
        TournamentSettings(concurrency=6, think_budget_per_deal=60),
        log=lambda m: None,
    )
    try:
        assert store.jobs_of("group")[0]["status"] == "queued"
        run_until(runner, store, "between")
        assert all(j["status"] == "done" for j in store.jobs_of("group"))
    finally:
        runner.close()


def test_a_failed_match_keeps_the_round_open(store):
    for t in "abc":
        fake(store, t)
    draw(store, group_size=8, seed=1)
    start_groups(store, deals=2)
    first = store.jobs_of("group")[0]
    store.claim_job_by_id(first["id"], "test")
    store.fail_job(first["id"], "boom")
    for other in store.jobs_of("group")[1:]:
        store.claim_job_by_id(other["id"], "test")
        store.finish_job(other["id"], {"mean_bb": 0.0}, None)
    assert settle(store) is None
    assert state_of(store)["phase"] == "groups"


def test_the_phase_survives_reopening_the_database(store):
    for t in "abcdef":
        fake(store, t)
    draw(store, group_size=3, seed=1)
    start_groups(store, deals=2)
    reopened = Store(store.root)  # a new process opening the same folder
    assert state_of(reopened)["phase"] == "groups"
    assert len(state_of(reopened)["groups"]) == 2
    assert len(reopened.jobs_of("group")) == 6


def test_status_reports_the_teams_and_how_far_it_is(store):
    for t in "abcdef":
        fake(store, t)
    assert status(store)["phase"] == "registration"
    draw(store, group_size=3, seed=1)
    start_groups(store, deals=2)
    report = status(store)
    assert report["phase"] == "groups" and len(report["teams"]) == 6
    assert report["matches"]["group"] == {"queued": 6}


def test_the_organiser_commands(tmp_path, capsys):
    from arena.cli import main

    root = str(tmp_path / "root")
    for t in "abcd":
        fake(Store(root), t)
    assert main(["tournament", "status", "--root", root]) == 0
    assert "4" in capsys.readouterr().out
    assert main(["tournament", "remove", "d", "--root", root]) == 0
    assert main(["tournament", "remove", "d", "--root", root]) == 2
    assert main(["tournament", "draw", "--root", root, "--seed", "5"]) == 0
    out = capsys.readouterr().out
    assert "drawn with seed 5" in out and "group A" in out
    assert main(["tournament", "draw", "--root", root]) == 2  # no silent redo
    assert main(["tournament", "start-groups", "--root", root]) == 0
    assert main(["tournament", "start-finals", "--root", root]) == 2
    assert "finals start" in capsys.readouterr().out
