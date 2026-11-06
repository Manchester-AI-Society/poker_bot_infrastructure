"""The two-round tournament, run with real websocket clients as the teams."""

from __future__ import annotations

import threading
import time

import pytest

from arena import connect as client
from arena import leaderboard
from arena.baselines import CallBot, FoldBot, ShoveBot
from arena.gateway import Gateway
from arena.store import Store
from arena.tournament import (
    Runner,
    TournamentError,
    TournamentSettings,
    balanced_sizes,
    draw,
    draw_groups,
    generate_keys,
    qualifiers,
    revealed,
    settle,
    start_finals,
    start_groups,
    state_of,
    status,
)

# -- the draw ----------------------------------------------------------------


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


# -- keys and phases -------------------------------------------------


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "data")


def test_keys_are_made_once_and_only_a_hash_is_kept(store):
    keys = generate_keys(store, ["fox", "owl"])
    assert set(keys) == {"fox", "owl"} and keys["fox"] != keys["owl"]
    assert all(len(k) >= 30 for k in keys.values())
    assert keys["fox"] not in " ".join(store.remote_teams().values())
    assert generate_keys(store, ["fox", "owl"]) == {}  # nothing new, no keys


def test_a_key_never_starts_with_a_dash(store):
    """A key starting with "-" is taken for a command-line option, so the
    client could not even start (found when a real team's key did)."""
    from arena.tournament import new_key

    keys = [new_key() for _ in range(5000)]
    assert not any(k.startswith("-") for k in keys)
    assert len(set(keys)) == len(keys)
    assert all(k.startswith("ak_") for k in keys)


def test_a_dash_leading_key_still_works_with_equals_syntax():
    """And if someone does hold such a key, --key=VALUE is accepted."""
    from arena.connect import main

    assert main(["--url", "ws://x", "--key=-abc"] + ["/no/such/bot"]) == 1


def test_a_key_can_be_rotated_and_the_old_one_stops_working(store):
    old = generate_keys(store, ["fox"])["fox"]
    new = generate_keys(store, [], rotate=["fox"])["fox"]
    assert new != old
    from arena.gateway import hash_key

    assert store.remote_teams()["fox"] == hash_key(new)
    with pytest.raises(TournamentError):
        generate_keys(store, [], rotate=["ghost"])


@pytest.mark.parametrize("name", ["Fox", "a b", "-x", "", "x" * 33, "a/b"])
def test_bad_team_names_are_refused(store, name):
    with pytest.raises(TournamentError):
        generate_keys(store, [name])


def test_the_draw_needs_teams_and_cannot_be_redone_silently(store):
    with pytest.raises(TournamentError):
        state_of(store)
    generate_keys(store, ["a"])
    with pytest.raises(TournamentError, match="two teams"):
        draw(store)
    generate_keys(store, ["b", "c", "d"])
    draw(store, group_size=2, seed=1)
    with pytest.raises(TournamentError, match="redo"):
        draw(store, group_size=2, seed=2)
    again = draw(store, group_size=2, seed=2, redo=True)
    assert again["seed"] == 2 and again["phase"] == "drawn"


def test_phases_must_come_in_order(store):
    generate_keys(store, ["a", "b", "c", "d"])
    with pytest.raises(TournamentError, match="draw"):
        start_groups(store)
    draw(store, group_size=2, seed=1)
    with pytest.raises(TournamentError, match="finals start"):
        start_finals(store)
    assert start_groups(store, deals=2) == 2  # two groups of two: 1 + 1
    with pytest.raises(TournamentError, match="final once"):
        draw(store, redo=True)
    with pytest.raises(TournamentError, match="draw"):
        start_groups(store)
    with pytest.raises(TournamentError, match="once play has begun"):
        generate_keys(store, ["late"])


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


# -- a whole tournament over real sockets --------------------------------

BOTS = {
    "fox": CallBot,
    "owl": FoldBot,
    "bear": ShoveBot,
    "wolf": CallBot,
    "mole": FoldBot,
    "hare": ShoveBot,
}


class Connected:
    """A team's bot on the real client, in a thread, logging its matches."""

    def __init__(self, gateway, team, key, bot):
        self.team = team
        self.logs = []
        self.stop = threading.Event()
        self.thread = threading.Thread(
            target=client.run,
            args=(bot, f"ws://127.0.0.1:{gateway.port}", key),
            kwargs=dict(log=self.logs.append, stop=self.stop.is_set),
            daemon=True,
        )
        self.thread.start()

    def matches(self):
        return [m for m in self.logs if m.startswith("match")]


@pytest.fixture
def arena(store):
    keys = generate_keys(store, sorted(BOTS))
    gateway = Gateway(store, "127.0.0.1", 0).start()
    teams = {
        name: Connected(gateway, name, keys[name], BOTS[name]())
        for name in BOTS
    }
    deadline = time.time() + 40
    while len(gateway.connected_teams()) < len(BOTS):
        assert time.time() < deadline, (
            "teams did not connect: "
            f"{sorted(gateway.connected_teams())} "
            f"{ {n: t.logs[-2:] for n, t in teams.items()} }"
        )
        time.sleep(0.02)
    yield store, gateway, teams
    for t in teams.values():
        t.stop.set()
    gateway.stop()


def run_until(runner, store, phase, seconds=90):
    deadline = time.time() + seconds
    while store.tournament()["phase"] != phase:
        assert time.time() < deadline, f"stuck at {store.tournament()}"
        runner.step()
        time.sleep(0.02)


def folders_apart(seed_range=range(1, 200)):
    """A seed whose groups of three each hold exactly one folder."""
    for seed in seed_range:
        groups = draw_groups(sorted(BOTS), 3, seed)
        if all(sum(t in ("owl", "mole") for t in g) == 1 for g in groups):
            return seed
    raise AssertionError("no such seed")


def test_a_full_tournament_groups_then_finals(arena):
    store, gateway, teams = arena
    draw(store, group_size=3, advance=2, seed=folders_apart())
    settings = TournamentSettings(
        deals_group=3, deals_final=3, grace_seconds=60
    )
    runner = Runner(store, gateway, settings, log=lambda m: None)

    assert start_groups(store, deals=3) == 6  # two groups of three: 3 + 3
    run_until(runner, store, "between")

    state = state_of(store)
    assert len(state["finalists"]) == 4
    # A folder loses to everyone, so neither folder reaches the final.
    assert "owl" not in state["finalists"] and "mole" not in state["finalists"]
    assert state["finalists"] == qualifiers(store, state)
    # Each group's table is complete and honest: callers beat folders.
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
    runner.close()

    # Everyone's bot played the matches it was scheduled for: a group team
    # played 2 group matches; a finalist 3 more.
    assert len(teams["fox"].matches()) % 2 == 0  # start/finish pairs
    # No team ever played two matches at the same time: its log alternates.
    for team in teams.values():
        kinds = [m.split()[1] for m in team.matches()]
        assert kinds[::2] == ["starting"] * len(kinds[::2])
        assert kinds[1::2] == ["finished"] * len(kinds[1::2])


def test_a_team_that_never_connects_forfeits_after_the_grace_period(store):
    keys = generate_keys(store, ["fox", "owl", "ghost"])
    gateway = Gateway(store, "127.0.0.1", 0).start()
    fox = Connected(gateway, "fox", keys["fox"], CallBot())
    owl = Connected(gateway, "owl", keys["owl"], CallBot())
    deadline = time.time() + 40
    while len(gateway.connected_teams()) < 2:
        assert time.time() < deadline
        time.sleep(0.02)
    try:
        draw(store, group_size=8, seed=1)
        start_groups(store, deals=3)
        now = [1000.0]
        state = state_of(store)
        state["started"]["groups"] = now[0]
        store.set_tournament(state)
        runner = Runner(
            store,
            gateway,
            TournamentSettings(grace_seconds=100),
            clock=lambda: now[0],
            log=lambda m: None,
        )
        runner.step()  # inside the grace period: only fox-owl can be played
        run_until_idle(runner)
        done = [j for j in store.jobs_of("group") if j["status"] == "done"]
        assert len(done) == 1  # the one match between connected teams

        now[0] += 101  # grace over: the ghost's matches are forfeited
        run_until(runner, store, "between")
        board = leaderboard.compute(
            store, "group", state_of(store)["groups"][0]["freeze"]
        )
        teams = {t["team"]: t for t in board["teams"]}
        assert board["teams"][-1]["team"] == "ghost"
        assert teams["ghost"]["score"] < -0.5
        assert teams["fox"]["score"] > 0 and teams["owl"]["score"] > 0
        runner.close()
    finally:
        fox.stop.set()
        owl.stop.set()
        gateway.stop()


def kick(gateway, team):
    """Disconnects a team for good (its client is told not to come back)."""
    import asyncio

    team.stop.set()
    link = gateway._links[team.team]
    asyncio.run_coroutine_threadsafe(
        link.ws.close(1011, "test"), gateway._loop
    ).result(5)


def run_until_idle(runner, seconds=60):
    """Steps until nothing is running and nothing more can be started."""
    deadline = time.time() + seconds
    store = runner.store

    def queued():
        return sum(
            1
            for kind in ("group", "final")
            for j in store.jobs_of(kind)
            if j["status"] == "queued"
        )

    while True:
        assert time.time() < deadline
        before = queued()
        runner.step()
        while not runner.idle():
            assert time.time() < deadline
            time.sleep(0.02)
            runner.step()
        runner.step()
        if queued() == before:
            return
        time.sleep(0.02)


def test_matches_wait_for_a_team_that_is_still_inside_its_grace(arena):
    store, gateway, teams = arena
    kick(gateway, teams["fox"])  # fox leaves
    deadline = time.time() + 10
    while "fox" in gateway.connected_teams():
        assert time.time() < deadline
        time.sleep(0.02)
    draw(store, group_size=8, seed=1)
    start_groups(store, deals=2)
    runner = Runner(
        store,
        gateway,
        TournamentSettings(grace_seconds=3600),
        log=lambda m: None,
    )
    run_until_idle(runner)
    jobs = store.jobs_of("group")
    fox_hash = store.get_version("remote-fox").hash
    waiting = [j for j in jobs if j["status"] == "queued"]
    assert waiting and all(
        fox_hash in (j["a_hash"], j["b_hash"]) for j in waiting
    )
    assert state_of(store)["phase"] == "groups"  # not finished without fox
    runner.close()


def test_a_failed_match_keeps_the_round_open(arena):
    store, gateway, _ = arena
    draw(store, group_size=8, seed=1)
    start_groups(store, deals=2)
    job = store.jobs_of("group")[0]
    store.claim_job_by_id(job["id"], "test")
    store.fail_job(job["id"], "boom")
    for other in store.jobs_of("group")[1:]:
        store.claim_job_by_id(other["id"], "test")
        store.finish_job(other["id"], {"mean_bb": 0.0}, None)
    assert settle(store) is None
    assert state_of(store)["phase"] == "groups"


def test_status_reports_who_is_connected_and_how_far_it_is(arena):
    store, gateway, _ = arena
    draw(store, group_size=3, seed=1)
    start_groups(store, deals=2)
    report = status(store)
    assert report["phase"] == "groups"
    assert all(report["teams"].values())  # all six are connected
    assert report["matches"]["group"] == {"queued": 6}
