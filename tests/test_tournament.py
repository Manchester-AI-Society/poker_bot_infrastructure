"""Tournament bracket, blind escalation, and all-in-on-blinds tests."""

from __future__ import annotations

import asyncio
import random
from collections import Counter
from typing import Any, Dict, List, Tuple

import pytest

from game.game_domain_models import MatchStateError
from game.game_service_core import GameService
from game.tournament import Tournament, split_into_tables

Sent = List[Tuple[str, Dict[str, Any]]]


def make_tournament() -> Tuple[GameService, Tournament, Sent]:
    service = GameService()
    sent: Sent = []

    async def send(player_id: str, event: Dict[str, Any]) -> None:
        sent.append((player_id, event))

    tournament = Tournament(service, send_cb=send)
    service.set_match_ended_handler(tournament.on_match_ended)
    return service, tournament, sent


async def drive_until_finished(
    service: GameService, tournament: Tournament, budget: int = 50_000
) -> None:
    """Check/calls every live turn across all tables until a champion."""
    for _ in range(budget):
        if tournament.status == "finished":
            return
        for table in list(tournament.tables):
            state = service.get_public_state(table["match_id"])
            player_id = state.get("current_player_id")
            if state.get("status") != "running" or player_id is None:
                continue
            viewer = service.get_public_state(
                table["match_id"], viewer_id=player_id
            )
            legal = viewer.get("legal_actions", [])
            await service.submit_action(
                match_id=table["match_id"],
                player_id=player_id,
                action="check" if "check" in legal else "call",
                amount=None,
                turn_id=state.get("turn_id"),
            )
    raise AssertionError("Tournament did not finish within the budget")


SETTINGS = dict(
    starting_stack=100,
    small_blind=5,
    big_blind=10,
    turn_timeout_seconds=3600,
    blind_increase_every_hands=2,
    max_hands=200,
)


class TestSplitting:
    @pytest.mark.parametrize(
        "count, expected_sizes",
        [
            (100, [10] * 10),
            (23, [3, 3, 3] + [2] * 7),
            (20, [2] * 10),
            (5, [3, 2]),
            (3, [3]),
            (2, [2]),
            (150, [15] * 10),
        ],
    )
    def test_tables_are_as_even_as_possible(self, count, expected_sizes):
        players = [f"p{i}" for i in range(count)]
        tables = split_into_tables(players)

        assert [len(t) for t in tables] == expected_sizes
        assert sorted(p for t in tables for p in t) == sorted(players)

    def test_needs_two_players(self):
        with pytest.raises(MatchStateError):
            split_into_tables(["solo"])


class TestBlindEscalation:
    def test_blinds_double_every_n_hands(self):
        async def scenario():
            service = GameService()
            runtime = service.create_match(
                player_ids=["a", "b"],
                starting_stack=10_000,
                small_blind=5,
                big_blind=10,
                turn_timeout_seconds=3600,
                blind_increase_every_hands=3,
                max_hands=7,
                wait_for_players=False,
            )
            await service.start_match(runtime.match_id, force=True)
            levels = {}
            while runtime.status != "finished":
                levels[runtime.engine.hand_number] = (
                    runtime.engine.big_blind_amount
                )
                state = service.get_public_state(runtime.match_id)
                player_id = state["current_player_id"]
                viewer = service.get_public_state(
                    runtime.match_id, viewer_id=player_id
                )
                await service.submit_action(
                    match_id=runtime.match_id,
                    player_id=player_id,
                    action="fold"
                    if "fold" in viewer["legal_actions"]
                    else "check",
                    amount=None,
                    turn_id=state["turn_id"],
                )
            return levels

        levels = asyncio.run(scenario())
        assert levels == {1: 10, 2: 10, 3: 10, 4: 20, 5: 20, 6: 20, 7: 40}


class TestAllInOnBlinds:
    def test_hand_with_no_one_to_act_settles_instead_of_stalling(self):
        random.seed(7)

        async def scenario():
            service = GameService()
            runtime = service.create_match(
                player_ids=["a", "b"],
                starting_stack=5,
                small_blind=10,
                big_blind=20,
                turn_timeout_seconds=3600,
                wait_for_players=False,
            )
            await service.start_match(runtime.match_id, force=True)
            return runtime

        runtime = asyncio.run(scenario())
        stacks = sorted(seat.curr_balance for seat in runtime.players)
        assert stacks in ([0, 10], [5, 5])
        if stacks == [0, 10]:
            assert runtime.status == "finished"
            assert len(runtime.winner_ids) == 1

    def test_short_stack_all_in_on_blind_keeps_cards(self):
        async def scenario():
            service = GameService()
            runtime = service.create_match(
                player_ids=["a", "b", "c"],
                starting_stack=100,
                small_blind=10,
                big_blind=20,
                turn_timeout_seconds=3600,
                wait_for_players=False,
            )
            runtime.players[2].curr_balance = 15  # big blind seat, short
            await service.start_match(runtime.match_id, force=True)
            return runtime

        runtime = asyncio.run(scenario())
        short = runtime.players[2]
        assert short.is_all_in
        assert not short.is_folded
        assert not short.is_eliminated
        assert len(short.cards) == 2


class TestTournament:
    def test_two_rounds_produce_one_champion(self):
        random.seed(2024)
        players = [f"bot{i}" for i in range(23)]

        async def scenario():
            service, tournament, sent = make_tournament()
            await tournament.start(players, **SETTINGS)
            round_one = [dict(t) for t in tournament.tables]
            assert tournament.round == 1
            await drive_until_finished(service, tournament)
            return tournament, round_one, sent

        tournament, round_one, sent = asyncio.run(scenario())

        assert len(round_one) == 10
        sizes = Counter(len(t["player_ids"]) for t in round_one)
        assert sizes == {3: 3, 2: 7}

        completed = tournament.history[0]
        winners = [t["winner"] for t in completed]
        assert all(w in t["player_ids"] for w, t in zip(winners, completed))
        final = tournament.tables[0]
        assert tournament.round == 2
        assert sorted(final["player_ids"]) == sorted(winners)
        assert tournament.champion == final["winner"]
        assert tournament.champion in winners
        assert tournament.status == "finished"

        by_player: Dict[str, List[str]] = {}
        for player_id, event in sent:
            by_player.setdefault(player_id, []).append(event["type"])
        for player_id in players:
            types = by_player[player_id]
            assert types[0] == "table_assigned"
            assert types[-1] == "tournament_ended"
            should_be_out = player_id != tournament.champion
            assert ("eliminated" in types) == should_be_out
        # Table winners get a second seat assignment for the final.
        assert by_player[tournament.champion].count("table_assigned") == 2

    def test_small_field_goes_straight_to_final(self):
        random.seed(3)

        async def scenario():
            service, tournament, _ = make_tournament()
            await tournament.start(["a", "b", "c"], **SETTINGS)
            assert tournament.round == 2
            await drive_until_finished(service, tournament)
            return tournament

        tournament = asyncio.run(scenario())
        assert tournament.champion in {"a", "b", "c"}
        assert tournament.history == []

    def test_admin_ending_a_table_still_advances(self):
        random.seed(5)

        async def scenario():
            service, tournament, _ = make_tournament()
            await tournament.start([f"p{i}" for i in range(4)], **SETTINGS)
            first = tournament.tables[0]["match_id"]
            await service.end_match(first, "admin", "test", "terminate_as_is")
            assert tournament.tables[0]["winner"] is not None
            await drive_until_finished(service, tournament)
            return tournament

        tournament = asyncio.run(scenario())
        assert tournament.status == "finished"
        assert tournament.champion is not None

    def test_cannot_start_twice_while_running(self):
        async def scenario():
            _, tournament, _ = make_tournament()
            await tournament.start(["a", "b", "c", "d"], **SETTINGS)
            with pytest.raises(MatchStateError):
                await tournament.start(["a", "b"], **SETTINGS)

        asyncio.run(scenario())
