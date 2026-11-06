"""Reproductions for the Critical/High findings in AUDIT.md.

Every test here asserts the *correct* behaviour and is currently marked
``xfail(strict=True)`` because the bug is still present. Strict means
that once a fix lands the test XPASSes, which fails the run until the
``xfail`` marker is removed -- so each fix has to graduate its own test.

Finding ids (C = critical, H = high) match AUDIT.md.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import List
from urllib.parse import parse_qs, urlparse

import pytest

from game.game_domain_models import InvalidActionError
from player_sdk.bot_interface import PokerBot
from player_sdk.client import PokerEngineClient, translate_action
from player_sdk.models import Action
from player_sdk.parser import GameStateParser

from .engine_helpers import (
    act,
    check_down,
    new_match,
    rig,
    showdown_winnings,
    stacks,
)

REPO_ROOT = Path(__file__).resolve().parents[1]

# --------------------------------------------------------------------------
# C1 -- no side pots / uncalled bets are not returned
# --------------------------------------------------------------------------


def test_c1_heads_up_uncalled_excess_is_returned():
    """600 into a 200 stack: only 200 can be won or lost."""

    async def scenario():
        service, runtime = await new_match([1000, 200])
        rig(runtime, {0: "7S 2D", 1: "AS AD"}, "KC 9D 4H 3C JS")
        await act(service, runtime, "raise_to", 600)  # p0 (not all-in)
        await act(service, runtime, "call")  # p1 calls all-in for 200
        await check_down(service, runtime)  # (see H1: p0 is still asked)
        return runtime

    runtime = asyncio.run(scenario())

    # p1 wins the 400 that was actually contested; p0 keeps the other 800.
    assert stacks(runtime) == [800, 400]


def test_c1_three_way_short_stack_wins_main_pot_only():
    """Short-stack all-in with the best hand must not win the side pot."""

    async def scenario():
        service, runtime = await new_match([100, 1000, 1000])
        # p0 best, p1 second best, p2 worst.
        rig(
            runtime,
            {0: "AS AD", 1: "KS KD", 2: "7C 2D"},
            "9H 8C 4D 3S JC",
        )
        await act(service, runtime, "raise_to", 100)  # p0 (button) shoves
        await act(service, runtime, "call")  # p1 (SB)
        await act(service, runtime, "call")  # p2 (BB)
        await act(service, runtime, "bet", 200)  # flop: p1 bets
        await act(service, runtime, "call")  # p2 calls
        await check_down(service, runtime)
        return runtime

    runtime = asyncio.run(scenario())

    # Main pot 300 -> p0.  Side pot 400 -> p1 (beats p2).
    assert showdown_winnings(runtime) == {"p0": 300, "p1": 400, "p2": 0}
    assert stacks(runtime) == [300, 1100, 700]


# --------------------------------------------------------------------------
# C2 -- an all-in raise ends the betting round; the opponent never responds
# --------------------------------------------------------------------------


def test_c2_opponent_must_answer_a_heads_up_shove():
    async def scenario():
        service, runtime = await new_match([200, 1000])
        await act(service, runtime, "raise_to", 200)  # p0 (SB) shoves
        return service, runtime

    service, runtime = asyncio.run(scenario())

    state = service.get_public_state(runtime.match_id, "p1")
    # p1 faces 180 more to call: the street must not have advanced and
    # "call" must be on the menu.
    assert state["street"] == "preflop"
    assert "call" in state.get("legal_actions", [])


# --------------------------------------------------------------------------
# C3 -- unauthenticated hole-card disclosure
# --------------------------------------------------------------------------


async def _asgi_get(app, path: str, query: str = "") -> tuple[int, dict]:
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": query.encode(),
        "headers": [],
        "client": ("127.0.0.1", 12345),
        "server": ("testserver", 80),
    }
    status = {"code": 0}
    chunks: List[bytes] = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        if message["type"] == "http.response.start":
            status["code"] = message["status"]
        elif message["type"] == "http.response.body":
            chunks.append(message.get("body", b""))

    await app(scope, receive, send)
    return status["code"], json.loads(b"".join(chunks) or b"{}")


@pytest.mark.xfail(
    strict=True, reason="AUDIT C3: viewer_id is unauthenticated"
)
def test_c3_state_endpoint_does_not_leak_other_players_hole_cards():
    from server.api.fastapi_application import app
    from server.api.shared_runtime_dependencies import games

    async def scenario():
        runtime = games.create_match(
            player_ids=["victim", "attacker"],
            turn_timeout_seconds=3600,
            wait_for_players=False,
        )
        await games.start_match(runtime.match_id, force=True)
        # No credentials at all, just claim to be the victim.
        return await _asgi_get(
            app,
            f"/v1/matches/{runtime.match_id}",
            "viewer_id=victim",
        )

    code, body = asyncio.run(scenario())
    assert code == 200
    victim = next(p for p in body["state"]["players"] if p["id"] == "victim")
    assert "hole_cards" not in victim


# --------------------------------------------------------------------------
# C4 -- an illegal action permanently disarms the turn timer
# --------------------------------------------------------------------------


def test_c4_turn_timer_survives_an_illegal_action():  # AUDIT C4 (fixed)
    async def scenario():
        service, runtime = await new_match([1000, 1000], timeout=1)
        with pytest.raises(InvalidActionError):
            # Below the minimum raise: rejected, as it should be ...
            await act(service, runtime, "raise_to", 21)
        # ... but the clock must keep running so a stuck bot is still
        # auto-folded/checked instead of freezing the match forever.
        await asyncio.sleep(1.6)
        return runtime

    runtime = asyncio.run(scenario())
    assert any(e["type"] == "timeout" for e in runtime.action_log)


# --------------------------------------------------------------------------
# H1 -- lone non-all-in player is prompted against an all-in opponent
# --------------------------------------------------------------------------


def test_h1_hand_runs_out_when_only_one_player_can_act():
    async def scenario():
        service, runtime = await new_match([1000, 200])
        await act(service, runtime, "raise_to", 200)  # p0 raises to 200
        await act(service, runtime, "call")  # p1 calls all-in; p0 matched
        return runtime

    runtime = asyncio.run(scenario())
    # Nothing left to decide: the board should run out and settle.
    assert runtime.status == "finished"


# --------------------------------------------------------------------------
# H2 -- a short stack cannot shove when its stack < the min-raise
# --------------------------------------------------------------------------


def test_h2_short_stack_can_shove_below_min_raise():
    async def scenario():
        service, runtime = await new_match([1000, 30])
        await act(service, runtime, "call")  # p0 limps
        # p1 (big blind, 30 total) has the option; min_raise_to is 40.
        state = service.get_public_state(runtime.match_id, "p1")
        assert state["max_raise_to"] == 30
        await act(service, runtime, "raise_to", state["max_raise_to"])
        return runtime

    asyncio.run(scenario())  # must not raise InvalidActionError


# --------------------------------------------------------------------------
# H3 -- big-blind option: engine advertises `bet`; SDK raise -> `bet`
# --------------------------------------------------------------------------


def test_h3_sdk_raise_from_big_blind_option_is_accepted():
    async def scenario():
        service, runtime = await new_match([1000, 1000])
        await act(service, runtime, "call")  # p0 limps, p1 has the option
        viewer = service.get_public_state(runtime.match_id, "p1")
        game_state = GameStateParser().parse(
            {"match_id": runtime.match_id, "state": viewer}, hero_index=1
        )
        engine_action, amount = translate_action(
            Action.raise_to(60), game_state
        )
        await service.submit_action(
            match_id=runtime.match_id,
            player_id="p1",
            action=engine_action,
            amount=amount,
            turn_id=viewer["turn_id"],
        )

    asyncio.run(scenario())  # must not raise InvalidActionError


# --------------------------------------------------------------------------
# H4 -- malformed `amount` (reachable over the websocket)
# --------------------------------------------------------------------------


@pytest.mark.xfail(strict=True, reason="AUDIT H4: non-int amount -> TypeError")
def test_h4_non_numeric_amount_is_an_invalid_action_not_a_crash():
    async def scenario():
        service, runtime = await new_match([1000, 1000])
        await act(service, runtime, "raise_to", "lots")  # type: ignore[arg-type]

    with pytest.raises(InvalidActionError):
        asyncio.run(scenario())


@pytest.mark.xfail(
    strict=True, reason="AUDIT H4: float amount creates fractional chips"
)
def test_h4_fractional_amount_is_rejected():
    async def scenario():
        service, runtime = await new_match([1000, 1000])
        await act(service, runtime, "raise_to", 45.5)  # type: ignore[arg-type]

    with pytest.raises(InvalidActionError):
        asyncio.run(scenario())


# --------------------------------------------------------------------------
# H5 -- .env is loaded after the server has already read its settings
# --------------------------------------------------------------------------


@pytest.mark.xfail(strict=True, reason="AUDIT H5: load_dotenv() runs too late")
def test_h5_dotenv_keys_are_used_by_the_server(tmp_path):
    for package in ("server", "game"):
        shutil.copytree(
            REPO_ROOT / package,
            tmp_path / package,
            ignore=shutil.ignore_patterns("__pycache__"),
        )
    (tmp_path / ".env").write_text(
        "BOT_API_KEYS=team-a:team-a-secret-key\n"
        "ADMIN_API_KEYS=root:root-secret-key\n"
    )
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in ("BOT_API_KEYS", "ADMIN_API_KEYS")
    }
    script = (
        "import json, server.run_poker_server;"
        "from server.api.shared_runtime_dependencies import"
        " api_keys, admin_api_keys;"
        "print(json.dumps([sorted(api_keys), sorted(admin_api_keys)]))"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    bot_keys, admin_keys = json.loads(result.stdout.strip().splitlines()[-1])
    assert bot_keys == ["team-a-secret-key"]
    assert admin_keys == ["root-secret-key"]  # not the public dev key


# --------------------------------------------------------------------------
# H9 -- SDK "recent" action history is actually the *first* 200 events
# --------------------------------------------------------------------------


class _NullBot(PokerBot):
    def act(self, game_state):  # pragma: no cover - never invoked
        return Action.fold()


@pytest.mark.xfail(
    strict=True, reason="AUDIT H9: history always read from offset 0"
)
def test_h9_action_history_includes_the_latest_actions():
    events = [
        {
            "type": "action",
            "player_id": "p0",
            "action": "call",
            "amount": index,
            "street": "preflop",
            "timestamp": float(index),
        }
        for index in range(500)
    ]
    client = PokerEngineClient(
        base_url="http://example.invalid",
        match_id="m",
        bot=_NullBot(),
        api_key="k",
    )

    def fake_request(method, path, payload=None, headers=None):
        query = parse_qs(urlparse(path).query)
        offset = int(query["offset"][0])
        limit = int(query["limit"][0])
        return {"events": events[offset : offset + limit], "total": 500}

    client._request = fake_request  # type: ignore[method-assign]

    history = client.fetch_action_history()
    assert history[-1]["amount"] == 499
