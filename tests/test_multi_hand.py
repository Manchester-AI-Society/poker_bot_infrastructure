"""Engine and service tests for multi-hand matches and start gating."""

from __future__ import annotations

import asyncio
import random
from typing import List, Optional

import pytest

from game.game_service_core import GameService
from game.match_runtime import MatchRuntime
from game.player import Player
from game.poker_game import PokerGame
from game.runtime_flow import begin_next_hand, eliminate_busted_players


def make_engine(
    balances: List[int], small_blind: int = 5, big_blind: int = 10
) -> PokerGame:
    players = [
        Player(curr_balance=balance, player_id=f"p{index}")
        for index, balance in enumerate(balances, start=1)
    ]
    return PokerGame(
        players=players,
        big_blind_amount=big_blind,
        small_blind_amount=small_blind,
    )


class TestButtonRotation:
    def test_first_hand_posts_blinds_in_order(self):
        game = make_engine([100, 100, 100, 100])
        game.start_hand()

        assert game.dealer_index == 0
        assert game.hand_number == 1
        sb = game.players[1]
        bb = game.players[2]
        assert sb.curr_bet_amount == 5
        assert bb.curr_bet_amount == 10
        assert game.pot == 15
        assert game.call_amount == 10
        # First to act preflop is the seat after the big blind.
        assert game.turn_index == 3

    def test_button_rotates_each_hand(self):
        game = make_engine([100, 100, 100, 100])
        game.start_hand()
        game.start_hand()

        assert game.hand_number == 2
        assert game.dealer_index == 1
        assert game.players[2].curr_bet_amount == 5
        assert game.players[3].curr_bet_amount == 10
        assert game.turn_index == 0

    def test_button_skips_busted_seat(self):
        game = make_engine([100, 100, 100, 100])
        game.start_hand()
        game.players[1].curr_balance = 0
        game.start_hand()

        assert game.dealer_index == 2
        assert game.players[3].curr_bet_amount == 5
        assert game.players[0].curr_bet_amount == 10
        # The busted seat receives no cards.
        assert game.players[1].cards == []

    def test_heads_up_button_posts_small_blind(self):
        game = make_engine([100, 100])
        game.start_hand()

        assert game.dealer_index == 0
        assert game.players[0].curr_bet_amount == 5
        assert game.players[1].curr_bet_amount == 10
        # Heads-up preflop: the button acts first.
        assert game.turn_index == 0

        game.advance_street()
        # Postflop: the non-button player acts first.
        assert game.turn_index == 1

    def test_heads_up_button_alternates(self):
        game = make_engine([100, 100])
        game.start_hand()
        game.start_hand()

        assert game.dealer_index == 1
        assert game.players[1].curr_bet_amount == 5
        assert game.players[0].curr_bet_amount == 10

    def test_short_stack_blind_is_capped_at_stack(self):
        game = make_engine([100, 100, 7])
        game.start_hand()

        bb = game.players[2]
        assert bb.curr_bet_amount == 7
        assert bb.curr_balance == 0
        assert bb.is_all_in
        assert game.pot == 12

    def test_all_players_broke_raises(self):
        game = make_engine([0, 0])
        with pytest.raises(ValueError):
            game.start_hand()


class TestElimination:
    def test_eliminate_busted_players_marks_folded(self):
        game = make_engine([50, 50, 50])
        runtime = MatchRuntime(
            match_id="m",
            engine=game,
            turn_timeout_seconds=3600,
            event_log_limit=100,
        )
        game.players[1].curr_balance = 0

        eliminated = eliminate_busted_players(
            runtime, lambda *args, **kwargs: None
        )

        assert eliminated == ["p2"]
        assert game.players[1].is_folded
        assert game.players[1].is_eliminated

    def test_elimination_is_logged_once_across_hands(self):
        game = make_engine([50, 0, 50])
        runtime = MatchRuntime(
            match_id="m",
            engine=game,
            turn_timeout_seconds=3600,
            event_log_limit=100,
        )
        logged: list[str] = []

        def log(_runtime, event_type, payload):
            if event_type == "player_eliminated":
                logged.append(payload["player_id"])

        begin_next_hand(runtime, log)
        begin_next_hand(runtime, log)
        begin_next_hand(runtime, log)

        assert logged == ["p2"]

    def test_begin_next_hand_deals_only_to_survivors(self):
        game = make_engine([50, 50, 50])
        runtime = MatchRuntime(
            match_id="m",
            engine=game,
            turn_timeout_seconds=3600,
            event_log_limit=100,
        )
        game.players[2].curr_balance = 0

        _, turn_player_id, _ = begin_next_hand(
            runtime, lambda *args, **kwargs: None
        )

        assert runtime.engine.hand_number == 1
        assert len(game.players[0].cards) == 2
        assert len(game.players[1].cards) == 2
        assert game.players[2].cards == []
        assert game.players[2].is_folded
        assert turn_player_id != "p3"


def passive_action(service: GameService, match_id: str) -> Optional[str]:
    """Returns the current player id, or None when no turn is live."""
    state = service.get_public_state(match_id)
    return state.get("current_player_id")


async def drive_passive_match(service: GameService, match_id: str) -> None:
    """Check/calls every turn until the match finishes."""
    for _ in range(5000):
        state = service.get_public_state(match_id)
        if state.get("status") == "finished":
            return
        player_id = state.get("current_player_id")
        if player_id is None:
            continue
        viewer = service.get_public_state(match_id, viewer_id=player_id)
        legal = viewer.get("legal_actions", [])
        action = "check" if "check" in legal else "call"
        await service.submit_action(
            match_id=match_id,
            player_id=player_id,
            action=action,
            amount=None,
            turn_id=state.get("turn_id"),
        )
    raise AssertionError("Match did not finish within the action budget")


class TestMultiHandMatches:
    def test_match_plays_until_bust_out(self):
        random.seed(1234)

        async def scenario() -> MatchRuntime:
            service = GameService()
            runtime = service.create_match(
                player_ids=["p1", "p2"],
                starting_stack=25,
                small_blind=5,
                big_blind=10,
                turn_timeout_seconds=3600,
                wait_for_players=False,
            )
            await service.start_match(runtime.match_id, force=True)
            await drive_passive_match(service, runtime.match_id)
            return runtime

        runtime = asyncio.run(scenario())

        stacks = [seat.curr_balance for seat in runtime.players]
        assert runtime.status == "finished"
        assert runtime.end_reason == "opponents_eliminated"
        assert sum(stacks) == 50
        assert max(stacks) == 50
        assert len(runtime.winner_ids) == 1

        events = list(runtime.action_log)
        hand_starts = [e for e in events if e["type"] == "hand_started"]
        assert len(hand_starts) >= 2
        assert [e["hand_number"] for e in hand_starts] == list(
            range(1, len(hand_starts) + 1)
        )
        assert [e for e in events if e["type"] == "match_ended"][-1][
            "reason"
        ] == "opponents_eliminated"

    def test_max_hands_cap_ends_match(self):
        random.seed(99)

        async def scenario() -> MatchRuntime:
            service = GameService()
            runtime = service.create_match(
                player_ids=["p1", "p2"],
                starting_stack=50,
                small_blind=5,
                big_blind=10,
                turn_timeout_seconds=3600,
                max_hands=2,
                wait_for_players=False,
            )
            await service.start_match(runtime.match_id, force=True)
            await drive_passive_match(service, runtime.match_id)
            return runtime

        runtime = asyncio.run(scenario())

        stacks = [seat.curr_balance for seat in runtime.players]
        assert runtime.status == "finished"
        assert runtime.end_reason == "hand_limit"
        assert runtime.engine.hand_number == 2
        assert sum(stacks) == 100
        assert runtime.winner_ids

        hand_starts = [
            e for e in runtime.action_log if e["type"] == "hand_started"
        ]
        assert len(hand_starts) == 2

    def test_invalid_max_hands_rejected(self):
        service = GameService()
        with pytest.raises(Exception):
            service.create_match(
                player_ids=["p1", "p2"],
                max_hands=0,
            )

    def test_chips_conserve_and_dealer_rotates(self):
        random.seed(7)

        async def scenario():
            service = GameService()
            runtime = service.create_match(
                player_ids=["p1", "p2"],
                starting_stack=40,
                small_blind=5,
                big_blind=10,
                turn_timeout_seconds=3600,
                max_hands=3,
                wait_for_players=False,
            )
            await service.start_match(runtime.match_id, force=True)
            await drive_passive_match(service, runtime.match_id)
            return runtime

        runtime = asyncio.run(scenario())

        assert sum(seat.curr_balance for seat in runtime.players) == 80
        hand_starts = [
            e for e in runtime.action_log if e["type"] == "hand_started"
        ]
        dealers = [e["dealer_index"] for e in hand_starts]
        assert dealers == [0, 1, 0]


class TestReadinessGate:
    def _make_service(self, connected: set) -> GameService:
        service = GameService()

        async def _noop(*args, **kwargs):
            return None

        service.set_event_handlers(
            broadcast_cb=_noop,
            direct_cb=_noop,
            connected_check=lambda player_id: player_id in connected,
        )
        return service

    def test_start_match_arms_until_all_connected(self):
        async def scenario():
            connected = {"p1"}
            service = self._make_service(connected)
            runtime = service.create_match(
                player_ids=["p1", "p2"], wait_for_players=True
            )

            result = await service.start_match(runtime.match_id)
            assert result["status"] == "waiting"
            assert result["armed"] is True
            assert runtime.status == "waiting"

            # The gateway registers the socket before notifying.
            connected.add("p2")
            await service.on_player_connected("p2")
            assert runtime.status == "running"

            await service.end_match(
                runtime.match_id, "admin", None, "terminate_as_is"
            )

        asyncio.run(scenario())

    def test_match_not_started_does_not_auto_start(self):
        async def scenario():
            service = self._make_service({"p1", "p2"})
            runtime = service.create_match(
                player_ids=["p1", "p2"], wait_for_players=True
            )

            await service.on_player_connected("p1")
            await service.on_player_connected("p2")
            assert runtime.status == "waiting"

        asyncio.run(scenario())

    def test_force_start_bypasses_gate(self):
        async def scenario():
            service = self._make_service(set())
            runtime = service.create_match(
                player_ids=["p1", "p2"], wait_for_players=True
            )

            result = await service.start_match(runtime.match_id, force=True)
            assert result["status"] == "running"
            assert runtime.status == "running"

            await service.end_match(
                runtime.match_id, "admin", None, "terminate_as_is"
            )

        asyncio.run(scenario())

    def test_wait_for_players_false_starts_immediately(self):
        async def scenario():
            service = self._make_service(set())
            runtime = service.create_match(
                player_ids=["p1", "p2"], wait_for_players=False
            )

            result = await service.start_match(runtime.match_id)
            assert result["status"] == "running"
            assert runtime.status == "running"

            await service.end_match(
                runtime.match_id, "admin", None, "terminate_as_is"
            )

        asyncio.run(scenario())

    def test_no_connection_layer_starts_immediately(self):
        async def scenario():
            service = GameService()
            runtime = service.create_match(player_ids=["p1", "p2"])

            result = await service.start_match(runtime.match_id)
            assert result["status"] == "running"
            assert runtime.status == "running"

            await service.end_match(
                runtime.match_id, "admin", None, "terminate_as_is"
            )

        asyncio.run(scenario())

    def test_disconnection_before_full_house_stays_armed(self):
        async def scenario():
            connected = set()
            service = self._make_service(connected)
            runtime = service.create_match(
                player_ids=["p1", "p2"], wait_for_players=True
            )

            await service.start_match(runtime.match_id)

            connected.add("p1")
            await service.on_player_connected("p1")
            assert runtime.status == "waiting"

            # p1 drops before p2 arrives.
            connected.discard("p1")
            connected.add("p2")
            await service.on_player_connected("p2")
            assert runtime.status == "waiting"

            # Everyone online at once: the match starts.
            connected.add("p1")
            await service.on_player_connected("p1")
            assert runtime.status == "running"

            await service.end_match(
                runtime.match_id, "admin", None, "terminate_as_is"
            )

        asyncio.run(scenario())
