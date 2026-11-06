"""The typed Response a bot returns, and its validation."""

from __future__ import annotations

import pytest

from arena.agents import AgentFault, LocalAgent
from arena.baselines import CallBot
from arena.bothost import act_on_message
from arena.contestant import Contestant
from arena.duel import PairingConfig, play_pairing
from player_sdk import Action, PokerBot, Response, translate_action
from player_sdk.models import GameState
from player_sdk.parser import GameStateParser
from player_sdk.response import InvalidResponse, validate_response


def state(**more) -> GameState:
    """A heads-up spot where we may fold, call or raise 40..2000."""
    base = dict(
        hole_cards=("AS", "KD"),
        community_cards=(),
        pot_size=30,
        stack_sizes=(1990, 1980),
        current_bets=(10, 20),
        current_player_index=0,
        call_amount=10,
        minimum_raise=20,
        action_history=(),
        legal_actions=("fold", "call", "raise_to"),
        my_index=0,
        min_raise_to=40,
        max_raise_to=2000,
    )
    base.update(more)
    return GameState(**base)


# -- the type ------------------


def test_the_four_ways_to_respond():
    assert Response.fold().action_type == "fold"
    assert Response.call().action_type == "call"
    assert Response.raise_to(120) == Response("raise", 120)
    assert Response.all_in().action_type == "all_in"


def test_the_old_name_is_the_same_type():
    assert Action is Response
    assert isinstance(Action.fold(), Response)


@pytest.mark.parametrize("amount", [0, -5, 1.5, "100", None, True])
def test_a_raise_needs_a_whole_positive_number_of_chips(amount):
    with pytest.raises(ValueError, match="whole number of chips"):
        Response.raise_to(amount)


def test_only_a_raise_carries_an_amount():
    for kind in ("fold", "call", "all_in"):
        with pytest.raises(ValueError, match="must not include an amount"):
            Response(kind, 50)


# -- validation ------------------


def test_legal_responses_pass_through_unchanged():
    s = state()
    for response in (
        Response.fold(),
        Response.call(),
        Response.raise_to(40),
        Response.raise_to(2000),
        Response.all_in(),
    ):
        assert validate_response(response, s) is response


@pytest.mark.parametrize(
    "returned",
    [None, "fold", {"action": "fold"}, ("raise", 100), 42, [Response.fold()]],
)
def test_anything_that_is_not_a_response_is_refused_with_advice(returned):
    with pytest.raises(InvalidResponse) as caught:
        validate_response(returned, state())
    message = str(caught.value)
    assert "must return a Response" in message
    assert "Response.raise_to(total)" in message


@pytest.mark.parametrize(
    "amount, word", [(39, "39"), (2001, "2001"), (5, "5")]
)
def test_a_raise_outside_the_range_names_the_range(amount, word):
    with pytest.raises(InvalidResponse) as caught:
        validate_response(Response.raise_to(amount), state())
    message = str(caught.value)
    assert word in message and "between 40 and 2000" in message


def test_raising_when_you_cannot_is_refused():
    facing_all_in = state(legal_actions=("fold", "call"))
    with pytest.raises(InvalidResponse, match="cannot bet or raise"):
        validate_response(Response.raise_to(100), facing_all_in)
    with pytest.raises(InvalidResponse, match="cannot bet or raise"):
        validate_response(Response.all_in(), facing_all_in)


def test_folding_or_calling_when_not_allowed_is_refused():
    with pytest.raises(InvalidResponse, match="cannot fold"):
        validate_response(Response.fold(), state(legal_actions=("check",)))
    with pytest.raises(InvalidResponse, match="cannot call or check"):
        validate_response(Response.call(), state(legal_actions=("fold",)))


# -- all in ------------------


def test_all_in_raises_to_the_maximum():
    assert translate_action(Response.all_in(), state()) == ("raise_to", 2000)
    first_to_act = state(legal_actions=("fold", "check", "bet"), call_amount=0)
    assert translate_action(Response.all_in(), first_to_act) == ("bet", 2000)


def test_all_in_when_you_can_only_call_calls():
    only_call = state(legal_actions=("fold", "call"), max_raise_to=None)
    assert translate_action(Response.all_in(), only_call) == ("call", None)


# -- in the arena: a mistake is a fault with a reason ------------------


class Bot(PokerBot):
    returns = None

    def act(self, game_state):
        return self.returns


def engine_message() -> dict:
    """An ``act`` message shaped like the engine's (what a bot is sent)."""
    return {
        "type": "act",
        "hero_index": 0,
        "state": {
            "players": [
                {"id": "p0", "stack": 1990, "bet": 10, "folded": False},
                {"id": "p1", "stack": 1980, "bet": 20, "folded": False},
            ],
            "hole_cards": ["AS", "KD"],
            "community_cards": [],
            "pot_size": 30,
            "current_player_index": 0,
            "call_amount": 10,
            "minimum_raise": 20,
            "legal_actions": ["fold", "call", "raise_to"],
            "min_raise_to": 40,
            "max_raise_to": 2000,
        },
        "action_history": [],
    }


def reply_for(returned):
    bot = Bot()
    bot.returns = returned
    return act_on_message(bot, GameStateParser(), engine_message())


def test_a_good_response_becomes_the_engine_move():
    assert reply_for(Response.raise_to(100)) == {
        "type": "action",
        "action": "raise_to",
        "amount": 100,
    }
    assert reply_for(Response.call())["action"] == "call"
    assert reply_for(Response.all_in())["amount"] == 2000


def test_a_bad_response_raises_the_validation_sentence():
    with pytest.raises(InvalidResponse, match="between 40 and 2000"):
        reply_for(Response.raise_to(5))
    with pytest.raises(InvalidResponse, match="must return a Response"):
        reply_for("raise")


class WrongSize(PokerBot):
    def act(self, game_state):
        return Response.raise_to(1)  # below the minimum, every time


def test_a_bot_with_a_bad_response_is_faulted_with_the_reason_and_plays_on():
    bot = Contestant(name="wrong", factory=lambda: LocalAgent(WrongSize))
    result = play_pairing(
        bot,
        Contestant(name="caller", factory=lambda: LocalAgent(CallBot)),
        PairingConfig(deals=2, seed=1, think_budget_per_deal=60),
    )
    assert result.status == "complete"
    assert result.faults_a > 0
    assert any("between" in line for line in result.fault_log_a)


def test_local_agent_reports_invalid_responses_as_agent_faults():
    class Returns(PokerBot):
        def act(self, game_state):
            return "fold"

    agent = LocalAgent(Returns)
    with pytest.raises(AgentFault, match="must return a Response"):
        agent.request(engine_message(), 1.0)


# -- safe_response: a live bot survives its own mistakes


def test_safe_response_passes_a_good_answer_through():
    from player_sdk.response import safe_response

    class Good(PokerBot):
        def act(self, game_state):
            return Response.raise_to(100)

    seen = []
    assert safe_response(Good(), state(), seen.append) == Response.raise_to(
        100
    )
    assert seen == []


def test_safe_response_replaces_a_crash_and_an_illegal_answer():
    from player_sdk.response import safe_move, safe_response

    class Crashes(PokerBot):
        def act(self, game_state):
            raise ValueError("oops")

    class Illegal(PokerBot):
        def act(self, game_state):
            return Response.raise_to(5)

    for bot in (Crashes(), Illegal()):
        seen = []
        got = safe_response(bot, state(), seen.append)
        assert got == Response.fold()  # facing a bet of 10
        assert len(seen) == 1 and "safe move" in seen[0]
    free = state(call_amount=0, legal_actions=("fold", "check", "raise_to"))
    assert safe_move(free) == Response.call()  # a free check
    assert safe_move(state()) == Response.fold()
