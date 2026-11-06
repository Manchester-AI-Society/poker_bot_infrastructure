"""Teams registering themselves with a join code, end to end."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest
from websockets.sync.client import connect

from arena import connect as client
from arena.baselines import CallBot
from arena.cli import main as cli_main
from arena.gateway import (
    MAX_REGISTER_FAILURES_PER_MINUTE,
    PROTOCOL,
    Gateway,
    hash_key,
)
from arena.store import Store
from arena.tournament import (
    TournamentError,
    close_registration,
    draw,
    generate_keys,
    open_registration,
    register_team,
    registration_is_open,
    remove_team,
    state_of,
)

CODE = "swordfish"
REPO = Path(__file__).resolve().parents[1]


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "data")


@pytest.fixture
def opened(store):
    open_registration(store, CODE)
    return store


@pytest.fixture
def gateway(opened):
    gw = Gateway(opened, "127.0.0.1", 0).start()
    yield gw
    gw.stop()


@pytest.fixture(autouse=True)
def arena_home(tmp_path, monkeypatch):
    """Teams' keys are saved here, never in the real home folder."""
    monkeypatch.setenv("ARENA_HOME", str(tmp_path / "arena_home"))


def wait_for(condition, seconds=30.0):
    deadline = time.time() + seconds
    while time.time() < deadline:
        if condition():
            return True
        time.sleep(0.02)
    return False


# -- the rules ---------------------------------------------------------------


def test_registration_is_closed_until_the_organiser_opens_it(store):
    assert registration_is_open(store) is False
    with pytest.raises(TournamentError, match="not open"):
        register_team(store, "fox", CODE)
    assert store.remote_teams() == {}


def test_a_team_with_the_code_gets_a_key_that_is_stored_hashed(opened):
    key = register_team(opened, "fox", CODE)
    assert key.startswith("ak_") and not key.startswith("-")
    assert opened.remote_teams() == {"fox": hash_key(key)}
    # The join code and the key are never kept in the clear.
    everything = json.dumps(opened.tournament()) + " ".join(
        opened.remote_teams().values()
    )
    assert CODE not in everything and key not in everything
    assert [v.team for v in opened.current_versions()] == ["fox"]


def test_the_join_code_must_be_right_and_whitespace_is_forgiven(opened):
    for wrong in ["", "nope", "SWORDFISH", None, 7]:
        with pytest.raises(TournamentError, match="join code"):
            register_team(opened, "fox", wrong)
    assert register_team(opened, "fox", f"  {CODE}\n")  # a copy-paste habit


@pytest.mark.parametrize(
    "name", ["Fox", "a b", "-x", "", "x" * 33, "a/b", "../x", None, 3]
)
def test_bad_team_names_are_refused(opened, name):
    with pytest.raises(TournamentError):
        register_team(opened, name, CODE)
    assert opened.remote_teams() == {}


def test_a_name_is_first_come_first_served(opened):
    register_team(opened, "fox", CODE)
    with pytest.raises(TournamentError, match="taken"):
        register_team(opened, "fox", CODE)


def test_registration_stops_at_the_cap(store):
    open_registration(store, CODE, max_teams=2)
    register_team(store, "a1", CODE)
    register_team(store, "b2", CODE)
    with pytest.raises(TournamentError, match="full"):
        register_team(store, "c3", CODE)


def test_the_organiser_can_close_registration(opened):
    register_team(opened, "fox", CODE)
    close_registration(opened)
    assert registration_is_open(opened) is False
    with pytest.raises(TournamentError, match="not open"):
        register_team(opened, "owl", CODE)


def test_drawing_the_groups_ends_registration(opened):
    register_team(opened, "fox", CODE)
    register_team(opened, "owl", CODE)
    draw(opened, group_size=8, seed=1)
    assert registration_is_open(opened) is False
    with pytest.raises(TournamentError, match="not open"):
        register_team(opened, "late", CODE)
    with pytest.raises(TournamentError, match="over"):
        open_registration(opened, CODE)


def test_a_team_can_be_removed_before_the_draw_only(opened):
    register_team(opened, "fox", CODE)
    register_team(opened, "owl", CODE)
    remove_team(opened, "fox")
    assert list(opened.remote_teams()) == ["owl"]
    assert [v.team for v in opened.current_versions()] == ["owl"]
    with pytest.raises(TournamentError, match="no team"):
        remove_team(opened, "fox")
    register_team(opened, "fox", CODE)  # the name is free again
    draw(opened, group_size=8, seed=1)
    with pytest.raises(TournamentError, match="before the draw"):
        remove_team(opened, "owl")


def test_a_short_code_is_refused_and_a_random_one_is_made(store):
    with pytest.raises(TournamentError, match="4 characters"):
        open_registration(store, "ab")
    code = open_registration(store)
    assert len(code) >= 6 and register_team(store, "fox", code)


def test_organiser_made_keys_and_self_registration_mix(opened):
    generate_keys(opened, ["owl"])
    register_team(opened, "fox", CODE)
    assert sorted(opened.remote_teams()) == ["fox", "owl"]
    assert state_of(opened)["registration"]["open"] is True


# -- over the websocket ------------------------


def url(gateway):
    return f"ws://127.0.0.1:{gateway.port}"


def first_reply(gateway, message):
    ws = connect(url(gateway))
    ws.send(json.dumps({"protocol": PROTOCOL, **message}))
    reply = json.loads(ws.recv(timeout=10))
    return ws, reply


def test_registering_over_the_socket_logs_the_team_in(gateway, opened):
    ws, reply = first_reply(
        gateway, {"type": "register", "team": "fox", "code": CODE}
    )
    assert reply["type"] == "registered" and reply["team"] == "fox"
    assert wait_for(lambda: gateway.is_connected("fox"))
    assert opened.remote_teams()["fox"] == hash_key(reply["key"])
    ws.close()
    # And the key it was handed works for an ordinary login.
    again, welcome = first_reply(
        gateway, {"type": "hello", "key": reply["key"]}
    )
    assert welcome == {"type": "welcome", "team": "fox"}
    again.close()


def test_a_wrong_code_is_refused_with_a_reason(gateway, opened):
    ws, reply = first_reply(
        gateway, {"type": "register", "team": "fox", "code": "nope"}
    )
    assert reply["type"] == "rejected" and "join code" in reply["message"]
    assert opened.remote_teams() == {}
    ws.close()


def test_guessing_the_code_is_throttled(gateway, opened):
    for _ in range(MAX_REGISTER_FAILURES_PER_MINUTE):
        ws, reply = first_reply(
            gateway, {"type": "register", "team": "fox", "code": "guess"}
        )
        assert "join code" in reply["message"]
        ws.close()
    # Now even the right code is refused for a while.
    ws, reply = first_reply(
        gateway, {"type": "register", "team": "fox", "code": CODE}
    )
    assert reply["type"] == "rejected" and "too many" in reply["message"]
    assert opened.remote_teams() == {}
    ws.close()


def test_registering_with_an_old_protocol_is_refused(gateway):
    ws, reply = first_reply(
        gateway,
        {"type": "register", "team": "fox", "code": CODE, "protocol": 0},
    )
    assert reply["type"] == "rejected" and "protocol" in reply["message"]
    ws.close()


# -- the team's side: the client ------------------------


def run_client(gateway, credentials):
    stop = threading.Event()
    logs = []
    result = {}

    def go():
        result["code"] = client.run(
            CallBot(),
            url(gateway),
            credentials,
            log=logs.append,
            stop=stop.is_set,
        )

    thread = threading.Thread(target=go, daemon=True)
    thread.start()
    return stop, logs, result, thread


def test_the_client_registers_saves_its_key_and_reuses_it(gateway, opened):
    creds = client.resolve_credentials(None, "fox", CODE)
    assert creds.key is None and creds.code == CODE
    stop, logs, _, _ = run_client(gateway, creds)
    try:
        assert wait_for(lambda: gateway.is_connected("fox"))
        saved = client.load_key("fox")
        assert saved and opened.remote_teams()["fox"] == hash_key(saved)
        assert any("registered team" in line for line in logs)
        mode = client.key_file("fox").stat().st_mode & 0o777
        assert mode in (0o600, 0o666, 0o644, 0o444)  # 0o600 off Windows
    finally:
        stop.set()
    # Next time only the team name is needed.
    again = client.resolve_credentials(None, "fox", None)
    assert again.key == saved


def test_running_the_register_command_twice_just_connects(gateway, opened):
    stop, _, _, _ = run_client(
        gateway, client.resolve_credentials(None, "fox", CODE)
    )
    try:
        assert wait_for(lambda: gateway.is_connected("fox"))
    finally:
        stop.set()
    # The same command again: a saved key exists, so no second registration
    # (which would fail with "taken").
    creds = client.resolve_credentials(None, "fox", CODE)
    assert creds.key and creds.code is None
    assert len(opened.remote_teams()) == 1


def test_credentials_prefer_an_explicit_key_then_a_saved_one():
    client.save_key("fox", "saved-key")
    assert client.resolve_credentials("given", "fox", "c").key == "given"
    assert client.resolve_credentials(None, "fox", "c").key == "saved-key"
    assert client.resolve_credentials(None, "owl", "c").code == "c"
    assert client.resolve_credentials(None, "owl", None) is None
    assert client.resolve_credentials(None, None, "c") is None


def test_the_client_command_explains_what_is_missing(capsys):
    code = client.main(
        ["--url", "ws://127.0.0.1:1", str(REPO / "bots/starter")]
    )
    assert code == 2
    assert "--team NAME --code" in capsys.readouterr().out


def test_the_client_command_exits_3_on_a_wrong_join_code(gateway, capsys):
    code = client.main(
        [
            "--url",
            url(gateway),
            "--team",
            "fox",
            "--code",
            "wrong",
            str(REPO / "bots/starter"),
        ]
    )
    assert code == client.EXIT_REJECTED
    assert "join code" in capsys.readouterr().out
    assert client.load_key("fox") is None  # nothing saved for a failure


# -- the organiser's commands ------------------------


def test_the_organiser_commands(tmp_path, capsys):
    root = str(tmp_path / "root")
    assert (
        cli_main(
            [
                "tournament",
                "open-registration",
                "--root",
                root,
                "--code",
                "letmein",
                "--max-teams",
                "10",
            ]
        )
        == 0
    )
    out = capsys.readouterr().out
    assert "join code: letmein" in out and "--code letmein" in out

    store = Store(root)
    register_team(store, "fox", "letmein")
    assert cli_main(["tournament", "status", "--root", root]) == 0
    status_out = capsys.readouterr().out
    assert "registration: open, 1 teams so far" in status_out

    assert cli_main(["tournament", "remove", "fox", "--root", root]) == 0
    assert cli_main(["tournament", "remove", "fox", "--root", root]) == 2
    assert "no team" in capsys.readouterr().out

    assert cli_main(["tournament", "close-registration", "--root", root]) == 0
    assert registration_is_open(Store(root)) is False
    assert (
        cli_main(
            ["tournament", "open-registration", "--root", root, "--code", "ab"]
        )
        == 2
    )
