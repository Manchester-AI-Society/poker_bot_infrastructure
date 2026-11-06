"""Zip bots playing in the live tournament as websocket clients."""

from __future__ import annotations

from pathlib import Path

import pytest

from arena import backup
from arena.backup import (
    BackupError,
    BackupRunner,
    TeamExists,
    plan,
    spawn_bot,
)
from arena.cli import main
from arena.store import Store


@pytest.fixture
def store(tmp_path):
    store = Store(tmp_path / "data")
    for team in ("fox", "owl", "bear"):
        folder = tmp_path / "bots" / team
        folder.mkdir(parents=True)
        store.add_version(team, f"h-{team}", str(folder), "valid", "")
        store.set_current(team, f"h-{team}")
    return store


class FakeServer:
    def __init__(self, lobby=(), existing=(), status="idle", script=()):
        self._lobby = list(lobby)
        self.existing = set(existing)
        self.status = status
        self.script = list(script)  # successive statuses, then the last
        self.created = {}
        self.rotated = {}
        self.fail = set()

    def lobby(self):
        return list(self._lobby)

    def tournament_status(self):
        if self.script:
            return (
                self.script.pop(0) if len(self.script) > 1 else self.script[0]
            )
        return self.status

    def create_player(self, name, key):
        if name in self.fail:
            raise BackupError(f"cannot create {name}: boom")
        if name in self.existing:
            raise TeamExists(name)
        self.created[name] = key

    def rotate_key(self, name, key):
        self.rotated[name] = key


class FakeProcess:
    def __init__(self, codes=()):
        self.codes = list(codes)  # successive poll() results
        self.terminated = False

    def poll(self):
        if self.terminated:
            return -15
        return self.codes.pop(0) if self.codes else None

    def terminate(self):
        self.terminated = True

    def wait(self, timeout=None):
        return 0

    def kill(self):
        self.terminated = True


class Spawner:
    def __init__(self, *scripts):
        self.scripts = list(scripts)
        self.calls = []

    def __call__(self, team, path, url, key, log_path):
        self.calls.append((team, Path(path), url, key, Path(log_path)))
        return FakeProcess(self.scripts.pop(0) if self.scripts else [])


def runner(store, server, spawner, **more):
    return BackupRunner(
        store,
        server,
        "http://server",
        spawn=spawner,
        log=lambda m: None,
        sleep=lambda s: None,
        **more,
    )


# -- who gets a backup bot ------------------


def test_only_teams_that_are_not_connected_live_are_run(store):
    chosen = plan(store, connected=["owl"])
    assert [t for t, _ in chosen.run] == ["bear", "fox"]
    assert chosen.skipped == [("owl", "already connected live")]


def test_all_runs_everyone_and_a_team_list_restricts(store):
    assert [t for t, _ in plan(store, ["owl"], only_missing=False).run] == [
        "bear",
        "fox",
        "owl",
    ]
    chosen = plan(store, [], teams=["fox", "ghost"])
    assert [t for t, _ in chosen.run] == ["fox"]
    assert chosen.skipped == [("ghost", "no imported bot")]


def test_a_team_with_a_failed_bot_has_no_backup(store, tmp_path):
    store.add_version("bad", "h-bad", "", "invalid", "crashed")
    assert "bad" not in [t for t, _ in plan(store, []).run]


# -- starting them ------------------


def test_each_team_becomes_a_player_with_its_own_secret_key(store):
    server, spawn = FakeServer(), Spawner()
    r = runner(store, server, spawn)
    problems = r.start(plan(store, []).run)
    assert problems == []
    assert sorted(server.created) == ["bear", "fox", "owl"]
    keys = list(server.created.values())
    assert len(set(keys)) == 3 and all(k.startswith("bk-") for k in keys)
    assert all(len(k) >= 30 for k in keys)
    for team, path, url, key, log_path in spawn.calls:
        assert url == "http://server" and key == server.created[team]
        assert path.name == team  # runs in the bot's own folder
        assert log_path == store.root / "logs" / team / "backup.log"


def test_a_name_that_is_already_a_player_is_not_taken_over_silently(store):
    server, spawn = FakeServer(existing=["fox"]), Spawner()
    r = runner(store, server, spawn)
    problems = r.start(plan(store, []).run)
    assert [t for t, _ in problems] == ["fox"]
    assert "--take-over" in problems[0][1]
    assert "fox" not in server.rotated and "fox" not in r.running
    assert sorted(r.running) == ["bear", "owl"]


def test_take_over_replaces_the_key_of_an_existing_player(store):
    server, spawn = FakeServer(existing=["fox"]), Spawner()
    r = runner(store, server, spawn)
    problems = r.start(plan(store, []).run, take_over=True)
    assert problems == [] and "fox" in server.rotated
    started_with = next(c[3] for c in spawn.calls if c[0] == "fox")
    assert started_with == server.rotated["fox"]


def test_a_failure_for_one_team_does_not_stop_the_others(store):
    server, spawn = FakeServer(), Spawner()
    server.fail.add("owl")
    r = runner(store, server, spawn)
    problems = r.start(plan(store, []).run)
    assert [t for t, _ in problems] == ["owl"]
    assert sorted(r.running) == ["bear", "fox"]


def test_keys_never_appear_in_the_log(store):
    server, spawn, lines = FakeServer(), Spawner(), []
    r = BackupRunner(
        store, server, "http://server", spawn=spawn, log=lines.append
    )
    r.start(plan(store, []).run)
    everything = "\n".join(lines)
    assert not any(key in everything for key in server.created.values())


# -- keeping them running ------------------


def test_a_bot_that_crashes_is_restarted_then_given_up_on(store):
    server = FakeServer(status="running")
    spawn = Spawner([1], [1], [1], [1])
    r = runner(store, server, spawn, max_restarts=2)
    r.start([("fox", store.root)])
    for _ in range(6):
        r.poll_once()
    assert len(spawn.calls) == 3  # the start + 2 restarts
    assert r.running["fox"].state == "failed"
    # Restarts reuse the same key, so the server still knows the bot.
    assert len({c[3] for c in spawn.calls}) == 1


def test_a_bot_that_exits_cleanly_is_finished_not_restarted(store):
    server = FakeServer(status="running")
    spawn = Spawner([0])
    r = runner(store, server, spawn)
    r.start([("fox", store.root)])
    r.poll_once()
    assert r.running["fox"].state == "finished" and len(spawn.calls) == 1


def test_nothing_is_restarted_once_the_tournament_is_over(store):
    server = FakeServer(status="running")
    spawn = Spawner([None, 1])  # runs, then exits with an error
    r = runner(store, server, spawn)
    r.start([("fox", store.root)])
    r.poll_once()  # the tournament is running; the bot is still up
    server.status = "finished"
    assert r.poll_once() == "finished"
    assert r.running["fox"].state == "finished" and len(spawn.calls) == 1


def test_an_earlier_events_finished_status_does_not_end_this_one(store):
    """The server still shows last time's champion when the backup bots start:
    that must not stop them before the new tournament has begun."""
    server = FakeServer(status="finished")
    spawn = Spawner([None, 1], [])  # the first process crashes at poll 2
    r = runner(store, server, spawn)
    r.start([("fox", store.root)])
    assert r.poll_once() == "waiting"  # last event's result, not ours
    assert r.running["fox"].state == "running"
    ticks = {"n": 0}

    def stop():
        ticks["n"] += 1
        if ticks["n"] == 3:
            server.status = "running"
        if ticks["n"] == 5:
            server.status = "finished"
        return ticks["n"] > 9

    r.supervise(stop=stop)
    # It kept going through the stale "finished", restarted the crashed bot,
    # and only ended after the NEW event ran and finished.
    assert len(spawn.calls) == 2
    assert 5 <= ticks["n"] <= 6


def test_supervising_ends_when_the_tournament_finishes_or_all_bots_end(store):
    server = FakeServer(status="running")
    spawn = Spawner([], [])
    r = runner(store, server, spawn)
    r.start([("fox", store.root), ("owl", store.root)])
    ticks = {"n": 0}

    def stop():
        ticks["n"] += 1
        if ticks["n"] == 2:
            server.status = "finished"
        return ticks["n"] > 5

    r.supervise(stop=stop)
    assert ticks["n"] <= 3  # it noticed the finish and returned

    # All bots ending on their own also ends the supervision.
    spawn2 = Spawner([0], [0])
    r2 = runner(store, FakeServer(status="running"), spawn2)
    r2.start([("fox", store.root), ("owl", store.root)])
    r2.supervise(stop=lambda: False)
    assert all(e.state == "finished" for e in r2.running.values())


def test_stop_all_terminates_what_is_still_running(store):
    spawn = Spawner([], [0])
    r = runner(store, FakeServer(), spawn)
    r.start([("fox", store.root), ("owl", store.root)])
    r.stop_all()
    assert r.running["fox"].process.terminated is True


# -- the real process launch ------------------


def test_the_bot_is_launched_as_a_websocket_client_in_its_own_folder(
    tmp_path, monkeypatch
):
    seen = {}

    class Popen:
        def __init__(self, command, **kwargs):
            seen["command"], seen["kwargs"] = command, kwargs

    monkeypatch.setattr(backup.subprocess, "Popen", Popen)
    folder = tmp_path / "botdir"
    folder.mkdir()
    spawn_bot("fox", folder, "https://x.example", "bk-123", tmp_path / "l.log")
    command = seen["command"]
    assert command[1:4] == ["-m", "player_sdk", "bot.py"]
    assert command[4:] == [
        "--tournament",
        "--server-url",
        "https://x.example",
        "--api-key",
        "bk-123",
    ]
    assert seen["kwargs"]["cwd"] == str(folder)
    assert str(backup.REPO_ROOT) in seen["kwargs"]["env"]["PYTHONPATH"]
    assert (tmp_path / "l.log").exists()


# -- the command ------------------


def test_the_command_needs_the_admin_key(store, capsys, monkeypatch):
    monkeypatch.delenv("POKER_ADMIN_API_KEY", raising=False)
    code = main(["backup-run", "--root", str(store.root)])
    assert code == 2 and "admin key" in capsys.readouterr().out


def test_the_command_reports_an_unreachable_server(store, capsys, monkeypatch):
    class Unreachable:
        def __init__(self, *args):
            raise ConnectionError("refused")

    monkeypatch.setattr(backup, "AdminServer", Unreachable)
    code = main(["backup-run", "--root", str(store.root), "--admin-key", "k"])
    assert code == 2 and "cannot reach the poker server" in (
        capsys.readouterr().out
    )


def test_the_command_runs_missing_teams_and_stops_at_the_end(
    store, capsys, monkeypatch
):
    server = FakeServer(lobby=["owl"], script=["idle", "running", "finished"])
    spawn = Spawner([], [])
    monkeypatch.setattr(backup, "AdminServer", lambda *a: server)
    monkeypatch.setattr(backup, "spawn_bot", spawn)
    code = main(["backup-run", "--root", str(store.root), "--admin-key", "k"])
    out = capsys.readouterr().out
    assert code == 0
    assert "skipping owl: already connected live" in out
    assert sorted(server.created) == ["bear", "fox"]
    assert "the tournament is finished" in out
