"""End-to-end tests that start a local server.

Run the full suite with:

    pytest

Skip these (unit tests only) with:

    pytest -m "not integration"
"""

from __future__ import annotations

import threading

import pytest

from admin_sdk import AdminSDKClient, AdminSDKConfiguration
from admin_sdk.models import MatchCreationOptions
from examples.bots.conservative_bot import ExampleConservativeBot
from player_sdk import play
from player_sdk.models import GameState
from player_sdk.testing import ensure_server_running, play_local_match

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def server_url() -> str:
    configuration = AdminSDKConfiguration.from_environment()
    ensure_server_running(configuration.base_url)
    return configuration.base_url


@pytest.fixture
def admin(server_url) -> AdminSDKClient:
    return AdminSDKClient(AdminSDKConfiguration.from_environment())


def create_match(
    admin: AdminSDKClient,
    *,
    starting_stack: int = 200,
    max_hands: int | None = None,
) -> str:
    created = admin.create_match(
        MatchCreationOptions(
            player_ids=["dev-bot-1", "dev-bot-2"],
            number_of_bots_allowed=2,
            starting_stack=starting_stack,
            small_blind=10,
            big_blind=20,
            turn_timeout_seconds=15,
            event_log_limit=5000,
            max_hands=max_hands,
        )
    )
    return str(created["match_id"])


class TestLocalMatchHarness:
    def test_two_bots_play_to_bust_out(self):
        result = play_local_match(
            [ExampleConservativeBot(), ExampleConservativeBot()],
            starting_stack=200,
            turn_timeout_seconds=8,
            max_duration_seconds=120,
        )
        assert result.status == "finished"
        assert result.winner_id is not None
        assert sum(result.final_stacks.values()) == 400
        assert max(result.final_stacks.values()) == 400

    def test_max_hands_caps_the_match(self, server_url, admin):
        result = play_local_match(
            [ExampleConservativeBot(), ExampleConservativeBot()],
            starting_stack=500,
            turn_timeout_seconds=8,
            max_hands=3,
            max_duration_seconds=120,
            verbose=False,
        )
        assert result.status == "finished"
        assert sum(result.final_stacks.values()) == 1000

        state = admin.get_full_match_state(result.match_id)["state"]
        events = admin._transport.request_json(
            "GET",
            f"/v1/matches/{result.match_id}/events?offset=0&limit=1000",
        )["events"]
        hand_starts = [e for e in events if e["type"] == "hand_started"]
        assert state["hand_number"] == 3
        assert len(hand_starts) == 3
        assert state["end_reason"] == "hand_limit"


class TestPlayOverWebsocket:
    def test_two_bots_play_via_play(self, server_url, admin):
        match_id = create_match(admin)
        results: dict[str, GameState] = {}
        errors: dict[str, BaseException] = {}

        def run_bot(api_key: str) -> None:
            try:
                results[api_key] = play(
                    model=ExampleConservativeBot(),
                    api_key=api_key,
                    server_url=server_url,
                    match_id=match_id,
                    transport="ws",
                    verbose=False,
                )
            except BaseException as exc:  # noqa: BLE001
                errors[api_key] = exc

        threads = [
            threading.Thread(target=run_bot, args=(key,), daemon=True)
            for key in ("dev-key-1", "dev-key-2")
        ]
        for thread in threads:
            thread.start()

        # Starting before the bots connect arms the match; the deal
        # happens automatically once both websockets are live, so the
        # first turn never races a cold-starting bot. (If both bots
        # managed to connect first, the start deals immediately.)
        started = admin.start_match(match_id)
        assert started["status"] in {"waiting", "running"}

        for thread in threads:
            thread.join(timeout=180)
        assert not errors, f"bot threads failed: {errors}"

        for api_key, state in results.items():
            assert state.status == "finished", api_key
            assert "status=finished" in state.summary
            assert "winner=" in state.summary

        stacks = {
            player_id: stack
            for state in results.values()
            for player_id, stack in zip(state.player_ids, state.stack_sizes)
        }
        assert sum(stacks.values()) == 400
        assert max(stacks.values()) == 400

        # A bust-out match must have played more than one hand.
        state = admin.get_full_match_state(match_id)["state"]
        assert state["hand_number"] >= 2
        assert state["end_reason"] == "opponents_eliminated"


class TestTournamentOverWebsocket:
    def test_twelve_remote_bots_play_a_two_round_tournament(
        self, server_url, admin
    ):
        import time

        from player_sdk import play_tournament

        keys = {}
        for index in range(12):
            player_id = f"tourney-bot-{index}"
            created = admin.create_player(
                player_id, api_key=f"{player_id}-key"
            )
            assert created["player_id"] == player_id
            keys[player_id] = f"{player_id}-key"

        results: dict[str, dict] = {}
        errors: dict[str, BaseException] = {}

        def run(player_id: str) -> None:
            try:
                results[player_id] = play_tournament(
                    ExampleConservativeBot(),
                    api_key=keys[player_id],
                    server_url=server_url,
                    verbose=False,
                )
            except BaseException as exc:  # noqa: BLE001
                errors[player_id] = exc

        threads = [
            threading.Thread(target=run, args=(pid,), daemon=True)
            for pid in keys
        ]
        for thread in threads:
            thread.start()

        deadline = time.time() + 30
        while set(keys) - set(admin.get_lobby()["players"]):
            assert time.time() < deadline, "bots never reached the lobby"
            time.sleep(0.1)

        bracket = admin.start_tournament(
            starting_stack=200,
            small_blind=5,
            big_blind=10,
            turn_timeout_seconds=8,
            blind_increase_every_hands=3,
            max_hands=200,
        )
        assert bracket["round"] == 1
        assert (
            sorted(len(t["player_ids"]) for t in bracket["tables"]) == [2] * 6
        )

        for thread in threads:
            thread.join(timeout=300)
        assert not errors, f"bot threads failed: {errors}"
        assert set(results) == set(keys)

        final = admin.get_tournament()
        assert final["status"] == "finished"
        round_one_winners = [t["winner"] for t in final["completed_rounds"][0]]
        assert len(round_one_winners) == 6
        assert sorted(final["tables"][0]["player_ids"]) == sorted(
            round_one_winners
        )
        champion = final["champion"]
        assert champion in round_one_winners

        assert results[champion]["type"] == "tournament_ended"
        assert results[champion]["champion"] == champion
        for player_id, outcome in results.items():
            if player_id != champion:
                assert outcome["type"] == "eliminated", player_id
