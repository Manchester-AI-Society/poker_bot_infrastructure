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


def create_match(admin: AdminSDKClient) -> str:
    created = admin.create_match(
        MatchCreationOptions(
            player_ids=["dev-bot-1", "dev-bot-2"],
            number_of_bots_allowed=2,
            starting_stack=1000,
            small_blind=10,
            big_blind=20,
            turn_timeout_seconds=15,
            event_log_limit=2000,
            table_label="pytest",
            tournament_round="integration",
        )
    )
    return str(created["match_id"])


class TestLocalMatchHarness:
    def test_two_bots_play_to_completion(self):
        result = play_local_match(
            [ExampleConservativeBot(), ExampleConservativeBot()],
            turn_timeout_seconds=8,
            max_duration_seconds=120,
        )
        assert result.status == "finished"
        assert result.winner_id is not None
        assert sum(result.final_stacks.values()) == 2000


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

        admin.start_match(match_id)

        for thread in threads:
            thread.join(timeout=120)
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
        assert sum(stacks.values()) == 2000
