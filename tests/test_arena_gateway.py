"""The websocket gateway and the team-side client, over real sockets."""

from __future__ import annotations

import json
import threading
import time

import pytest
from websockets.sync.client import connect

from arena import connect as client
from arena.agents import AgentCrashed, AgentFault, AgentTimeout
from arena.baselines import CallBot, FoldBot
from arena.contestant import Contestant
from arena.duel import PairingConfig, play_pairing
from arena.gateway import PROTOCOL, Gateway, hash_key
from arena.store import Store
from player_sdk.bot_interface import PokerBot
from player_sdk.models import Action

KEYS = {"fox": "fox-secret", "owl": "owl-secret"}


@pytest.fixture
def store(tmp_path):
    store = Store(tmp_path / "data")
    for team, key in KEYS.items():
        store.add_remote_team(team, hash_key(key))
    return store


@pytest.fixture
def gateway(store):
    gw = Gateway(store, "127.0.0.1", 0).start()
    yield gw
    gw.stop()


def url(gateway):
    return f"ws://127.0.0.1:{gateway.port}"


def wait_for(condition, seconds=30.0):
    deadline = time.time() + seconds
    while time.time() < deadline:
        if condition():
            return True
        time.sleep(0.02)
    return False


class Team:
    """A team's bot connected through the real client, in a thread."""

    def __init__(self, gateway, team, bot):
        self.stop = threading.Event()
        self.logs = []
        self.code = None
        self.thread = threading.Thread(
            target=self._run, args=(gateway, team, bot), daemon=True
        )
        self.thread.start()
        assert wait_for(lambda: gateway.is_connected(team)), "no connect"

    def _run(self, gateway, team, bot):
        self.code = client.run(
            bot,
            url(gateway),
            KEYS[team],
            log=self.logs.append,
            stop=self.stop.is_set,
        )

    def close(self):
        self.stop.set()


@pytest.fixture
def team(gateway):
    made = []

    def make(name, bot):
        t = Team(gateway, name, bot)
        made.append(t)
        return t

    yield make
    for t in made:
        t.close()


# -- connecting ----------------------------------------------------------


def hello(gateway, key, protocol=PROTOCOL):
    ws = connect(url(gateway))
    ws.send(json.dumps({"type": "hello", "key": key, "protocol": protocol}))
    return ws, json.loads(ws.recv(timeout=5))


def test_a_valid_key_is_welcomed_and_shown_as_connected(gateway, store):
    ws, reply = hello(gateway, KEYS["fox"])
    assert reply == {"type": "welcome", "team": "fox"}
    assert wait_for(lambda: gateway.is_connected("fox"))
    assert store.presences()["fox"]["connected"] is True
    ws.close()
    assert wait_for(lambda: not gateway.is_connected("fox"))
    assert wait_for(lambda: not store.presences()["fox"]["connected"])


@pytest.mark.parametrize("key", ["", "nope", "fox-secret ", None, 7])
def test_a_wrong_key_is_refused(gateway, key):
    ws, reply = hello(gateway, key)
    assert reply["type"] == "rejected"
    assert gateway.connected_teams() == set()
    ws.close()


def test_an_old_protocol_is_refused_with_a_clear_message(gateway):
    ws, reply = hello(gateway, KEYS["fox"], protocol=0)
    assert reply["type"] == "rejected" and "protocol" in reply["message"]
    ws.close()


def test_garbage_before_hello_closes_the_connection(gateway):
    ws = connect(url(gateway))
    ws.send("not json")
    with pytest.raises(Exception):
        ws.recv(timeout=5)
    assert gateway.connected_teams() == set()


def test_keys_are_stored_hashed_never_in_clear(store):
    stored = store.remote_teams()
    assert stored["fox"] == hash_key("fox-secret")
    assert "fox-secret" not in " ".join(stored.values())


def test_a_second_connection_replaces_the_first(gateway):
    first, _ = hello(gateway, KEYS["fox"])
    assert wait_for(lambda: gateway.is_connected("fox"))
    second, reply = hello(gateway, KEYS["fox"])
    assert reply["type"] == "welcome"
    with pytest.raises(Exception):
        while True:
            first.recv(timeout=5)
    assert gateway.is_connected("fox")
    second.close()


def test_the_client_exits_with_a_clear_code_on_a_bad_key(gateway):
    logs = []
    code = client.run(CallBot(), url(gateway), "wrong", log=logs.append)
    assert code == client.EXIT_REJECTED
    assert any("refused" in line for line in logs)


# -- playing -------------------------------------------------------------


def remote(gateway, name, **kwargs):
    kwargs.setdefault("move_timeout", 5.0)
    return Contestant(name=name, factory=lambda: gateway.agent(name), **kwargs)


def local(name, bot_class):
    from arena.agents import LocalAgent

    return Contestant(name=name, factory=lambda: LocalAgent(bot_class))


def test_a_remote_bot_plays_a_full_pairing_over_the_socket(gateway, team):
    team("fox", CallBot())
    result = play_pairing(
        remote(gateway, "fox"),
        local("folder", FoldBot),
        PairingConfig(deals=5, seed=3, think_budget_per_deal=60),
    )
    assert result.status == "complete"
    assert result.faults_a == 0 and result.deals_completed == 5
    # A caller beats a folder by exactly three quarters of a big blind.
    assert result.mean_bb == pytest.approx(0.75)


def test_two_remote_bots_play_each_other(gateway, team):
    team("fox", CallBot())
    team("owl", FoldBot())
    result = play_pairing(
        remote(gateway, "fox"),
        remote(gateway, "owl"),
        PairingConfig(deals=4, seed=9, think_budget_per_deal=60),
    )
    assert result.faults_a == 0 and result.faults_b == 0
    assert result.mean_bb == pytest.approx(0.75)


def test_a_remote_result_equals_the_same_bots_played_locally(gateway, team):
    team("fox", CallBot())
    config = PairingConfig(deals=6, seed=5, think_budget_per_deal=60)
    over_socket = play_pairing(
        remote(gateway, "fox"), local("folder", FoldBot), config
    )
    in_process = play_pairing(
        local("fox", CallBot), local("folder", FoldBot), config
    )
    assert over_socket.mean_bb == in_process.mean_bb
    assert over_socket.hands_played == in_process.hands_played


class Slow(PokerBot):
    def act(self, game_state):
        time.sleep(0.6)
        return Action.call()


class Crasher(PokerBot):
    def act(self, game_state):
        raise RuntimeError("boom")


def test_a_slow_bot_times_out_and_is_faulted_not_waited_for(gateway, team):
    team("fox", Slow())
    contestant = remote(gateway, "fox", move_timeout=0.2)
    started = time.time()
    result = play_pairing(
        contestant,
        local("caller", CallBot),
        PairingConfig(deals=2, seed=1, think_budget_per_deal=60),
    )
    assert result.faults_a > 0
    assert any("no reply" in line for line in result.fault_log_a)
    assert time.time() - started < 30


def test_a_bot_that_raises_costs_a_fault_and_the_match_goes_on(gateway, team):
    t = team("fox", Crasher())
    result = play_pairing(
        remote(gateway, "fox"),
        local("caller", CallBot),
        PairingConfig(deals=2, seed=1, think_budget_per_deal=60),
    )
    assert result.status == "complete" and result.faults_a > 0
    assert any("boom" in line for line in result.fault_log_a)
    assert t.thread.is_alive()  # the client survived its bot's exception


def test_a_team_that_is_not_connected_is_a_crash_not_a_hang(gateway):
    started = time.time()
    with pytest.raises(AgentCrashed):
        gateway.exchange("owl", {"type": "act"}, 1.0)
    assert time.time() - started < 2


def test_a_late_reply_is_never_taken_for_the_next_moves_reply(gateway):
    """Replies carry the id of their request; a stale one is ignored."""
    ws, _ = hello(gateway, KEYS["fox"])
    assert wait_for(lambda: gateway.is_connected("fox"))
    outcome = {}

    def ask():
        try:
            gateway.exchange("fox", {"type": "act"}, 0.3)
        except AgentTimeout:
            outcome["first"] = "timeout"
        try:
            outcome["second"] = gateway.exchange("fox", {"type": "act"}, 3.0)
        except AgentFault as exc:
            outcome["second"] = exc

    thread = threading.Thread(target=ask)
    thread.start()
    first = json.loads(ws.recv(timeout=5))
    # Answer the FIRST request only after it has timed out...
    time.sleep(0.6)
    ws.send(
        json.dumps(
            {
                "type": "action",
                "id": first["id"],
                "action": "fold",
                "amount": None,
            }
        )
    )
    second = json.loads(ws.recv(timeout=5))
    assert second["id"] != first["id"]
    ws.send(
        json.dumps(
            {
                "type": "action",
                "id": second["id"],
                "action": "call",
                "amount": None,
            }
        )
    )
    thread.join(timeout=10)
    assert outcome["first"] == "timeout"
    assert outcome["second"]["action"] == "call"  # not the stale fold
    ws.close()


def test_a_reply_without_the_right_id_is_ignored(gateway):
    ws, _ = hello(gateway, KEYS["fox"])
    assert wait_for(lambda: gateway.is_connected("fox"))
    result = {}

    def ask():
        try:
            result["r"] = gateway.exchange("fox", {"type": "act"}, 0.5)
        except AgentFault as exc:
            result["r"] = exc

    thread = threading.Thread(target=ask)
    thread.start()
    request = json.loads(ws.recv(timeout=5))
    ws.send(
        json.dumps(
            {"type": "action", "id": request["id"] + 99, "action": "call"}
        )
    )
    ws.send(json.dumps({"type": "action", "action": "call"}))  # no id
    thread.join(timeout=10)
    assert isinstance(result["r"], AgentTimeout)
    ws.close()


def test_the_client_reconnects_after_the_connection_drops(gateway, team):
    t = team("fox", CallBot())
    # Drop the team from the server side; the client must come back.
    link = gateway._links["fox"]
    import asyncio

    asyncio.run_coroutine_threadsafe(
        link.ws.close(1011, "test"), gateway._loop
    ).result(5)
    assert wait_for(
        lambda: (
            not gateway.is_connected("fox")
            or gateway._links["fox"] is not link
        )
    )
    assert wait_for(
        lambda: (
            gateway.is_connected("fox") and gateway._links["fox"] is not link
        ),
        seconds=10,
    )
    assert any("connection lost" in line for line in t.logs)


def test_the_client_survives_a_connection_dropped_during_the_handshake():
    """A flaky network can cut the TCP connection before the websocket is
    up; that raised EOFError and used to end the team's client for good."""
    import socket

    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(5)
    port = listener.getsockname()[1]
    accepted = []

    def slam():
        while len(accepted) < 3:
            conn, _ = listener.accept()
            accepted.append(1)
            conn.close()  # no HTTP reply at all

    threading.Thread(target=slam, daemon=True).start()
    logs, stop = [], threading.Event()
    # Don't wait out the client's backoff between attempts.
    original = client.RECONNECT_FIRST_SECONDS
    client.RECONNECT_FIRST_SECONDS = 0.05
    try:
        runner = threading.Thread(
            target=client.run,
            args=(CallBot(), f"ws://127.0.0.1:{port}", "k"),
            kwargs=dict(log=logs.append, stop=stop.is_set),
            daemon=True,
        )
        runner.start()
        assert wait_for(lambda: len(accepted) >= 3, seconds=10)
        assert runner.is_alive()  # still trying, not dead
        stop.set()
        runner.join(timeout=10)
    finally:
        client.RECONNECT_FIRST_SECONDS = original
        listener.close()
    assert sum("connection lost" in line for line in logs) >= 2
