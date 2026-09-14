"""Tests for Action validation and GameState helpers."""

from __future__ import annotations

import pytest

from player_sdk.models import Action, ActionRecord, GameState


def make_state(**overrides) -> GameState:
    defaults = dict(
        hole_cards=("As", "Kd"),
        community_cards=(),
        pot_size=30,
        stack_sizes=(1000, 1000),
        current_bets=(20, 10),
        current_player_index=0,
        call_amount=10,
        minimum_raise=20,
        action_history=(
            ActionRecord(player_id="p2", action="bet", amount=10),
        ),
        turn_id=3,
        legal_actions=("fold", "call", "raise_to"),
        my_index=0,
        street="preflop",
        status="running",
        player_ids=("p1", "p2"),
    )
    defaults.update(overrides)
    return GameState(**defaults)


class TestAction:
    def test_fold_call_raise_constructors(self):
        assert Action.fold().action_type == "fold"
        assert Action.call().action_type == "call"
        assert Action.raise_to(60).amount == 60

    def test_raise_requires_positive_amount(self):
        with pytest.raises(ValueError):
            Action("raise", amount=0)
        with pytest.raises(ValueError):
            Action("raise")

    def test_fold_call_reject_amount(self):
        with pytest.raises(ValueError):
            Action("fold", amount=5)


class TestGameStateHelpers:
    def test_my_stack_and_bet_use_my_index(self):
        state = make_state()
        assert state.my_stack == 1000
        assert state.my_bet == 20

    def test_is_my_turn(self):
        assert make_state().is_my_turn
        assert not make_state(current_player_index=1).is_my_turn

    def test_can_helpers(self):
        state = make_state()
        assert state.can_fold and state.can_call and state.can_raise
        assert not state.can_check and not state.can_bet

    def test_street_helpers(self):
        assert make_state().is_preflop
        assert make_state(
            street=None, community_cards=("2s", "3s", "4s")
        ).is_flop
        assert make_state(
            street=None, community_cards=("2s", "3s", "4s", "5s")
        ).is_turn
        assert make_state(
            street=None,
            community_cards=("2s", "3s", "4s", "5s", "6s"),
        ).is_river


class TestSummary:
    def test_summary_names_winner_and_stacks(self):
        summary = make_state(
            status="finished",
            stack_sizes=(1200, 800),
        ).summary
        assert "status=finished" in summary
        assert "winner=p1" in summary
        assert "1200" in summary and "800" in summary

    def test_summary_ranks_by_stack(self):
        summary = make_state(
            status="finished",
            stack_sizes=(300, 1700),
        ).summary
        assert "winner=p2" in summary
        assert summary.index("p2=1700") < summary.index("p1=300")

    def test_summary_without_player_ids_uses_seat_labels(self):
        summary = make_state(
            player_ids=(None, None),
            status="finished",
        ).summary
        assert "winner=seat 0" in summary

    def test_summary_with_no_stacks(self):
        summary = make_state(stack_sizes=()).summary
        assert summary.startswith("status=")
