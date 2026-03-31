from __future__ import annotations

import asyncio
from typing import Any, Dict, Iterable, Optional, Tuple

from server.game import GameService
from server.schemas import CreateMatchRequest


RANK_NAMES = {
    "2": "Two",
    "3": "Three",
    "4": "Four",
    "5": "Five",
    "6": "Six",
    "7": "Seven",
    "8": "Eight",
    "9": "Nine",
    "T": "Ten",
    "J": "Jack",
    "Q": "Queen",
    "K": "King",
    "A": "Ace",
}

SUIT_NAMES = {
    "S": "Spades",
    "H": "Hearts",
    "D": "Diamonds",
    "C": "Clubs",
}


def human_card(card: str) -> str:
    if len(card) != 2:
        return card
    rank = RANK_NAMES.get(card[0], card[0])
    suit = SUIT_NAMES.get(card[1], card[1])
    return f"{rank} of {suit}"


def human_cards(cards: Iterable[str]) -> str:
    items = [human_card(card) for card in cards]
    if not items:
        return "No board cards yet"
    return ", ".join(items)


def human_action(action: str, amount: Optional[int]) -> str:
    if action == "fold":
        return "folds"
    if action == "check":
        return "checks"
    if action == "call":
        return "calls"
    if action == "bet":
        return f"bets to {amount} chips"
    if action == "raise_to":
        return f"raises to {amount} chips"
    return action


class DemoEventBus:
    """Prints readable, narrated game events."""

    def __init__(self) -> None:
        self.broadcast_count = 0
        self.direct_count = 0
        self.current_street = "preflop"

    async def broadcast(self, player_ids: Iterable[str], payload: Dict[str, Any]) -> None:
        self.broadcast_count += 1
        event_type = payload.get("type")

        if event_type == "action":
            player_id = payload.get("player_id", "unknown")
            action = payload.get("action", "unknown")
            amount = payload.get("amount")

            if action == "post_small_blind":
                print(f"Table update: {player_id} posts the small blind ({amount} chips).")
                return
            if action == "post_big_blind":
                print(f"Table update: {player_id} posts the big blind ({amount} chips).")
                return

            if amount is None:
                print(f"Table update: {player_id} {human_action(action, amount)}.")
            else:
                print(f"Table update: {player_id} {human_action(action, amount)}.")
            return

        if event_type == "timeout":
            player_id = payload.get("player_id", "unknown")
            print(f"Timeout: {player_id} ran out of time. The server auto-played a safe action.")
            return

        if event_type == "showdown":
            print("\nShowdown reached. Final results:")
            for result in payload.get("results", []):
                player = result.get("player_id", "unknown")
                hand = result.get("hand", "Unknown Hand")
                winnings = result.get("winnings", 0)
                print(f"- {player}: {hand}, winnings {winnings} chips")
            board = payload.get("board")
            if board:
                print(f"Final board: {human_cards(board)}")
            return

        print(f"System event: {payload}")

    async def direct(self, player_id: str, payload: Dict[str, Any]) -> None:
        self.direct_count += 1
        event_type = payload.get("type")

        if event_type != "your_turn":
            print(f"Direct event to {player_id}: {payload}")
            return

        turn_id = payload.get("turn_id")
        state = payload.get("state", {})
        street = state.get("street", "unknown")
        pot = state.get("pot", 0)
        board = state.get("board", [])
        legal_actions = state.get("legal_actions", [])
        hole_cards = state.get("hole_cards", [])

        if street != self.current_street:
            self.current_street = street
            print(f"\nNew betting round: {street.upper()}")

        print(f"\nTurn {turn_id}: It is {player_id}'s move.")
        print(f"- Pot: {pot} chips")
        print(f"- Board: {human_cards(board)}")
        print(f"- Your hole cards: {human_cards(hole_cards)}")
        print(f"- Legal actions: {', '.join(legal_actions)}")


def choose_action(state: Dict[str, Any]) -> Tuple[str, Optional[int]]:
    """
    Deterministic demo strategy to exercise legal action paths.

    Priority:
    1) check
    2) call
    3) bet minimum
    4) raise_to minimum
    5) fold
    """

    legal_actions = state.get("legal_actions", [])

    if "check" in legal_actions:
        return "check", None
    if "call" in legal_actions:
        return "call", None
    if "bet" in legal_actions:
        return "bet", int(state.get("min_raise_to", 20))
    if "raise_to" in legal_actions:
        return "raise_to", int(state.get("min_raise_to", 20))
    return "fold", None


async def run_demo_hand() -> None:
    event_bus = DemoEventBus()
    game = GameService()
    game.set_event_handlers(broadcast_cb=event_bus.broadcast, direct_cb=event_bus.direct)

    create_request = CreateMatchRequest(
        player_ids=["dev-bot-1", "dev-bot-2"],
        starting_stack=1000,
        small_blind=10,
        big_blind=20,
        turn_timeout_seconds=10,
    )

    match = game.create_match(create_request)
    print("Poker Demo")
    print("-" * 60)
    print(f"Created match {match.match_id} with players: {', '.join(create_request.player_ids)}")
    print(
        f"Starting stacks: {create_request.starting_stack} chips each, "
        f"blinds {create_request.small_blind}/{create_request.big_blind}"
    )

    await game.start_match(match.match_id)
    print("Hand started. The demo bot logic will now auto-play legal actions.")

    max_actions = 200
    action_counter = 0

    while action_counter < max_actions:
        public_state = game.get_public_state(match.match_id)
        if public_state["status"] == "finished":
            break

        acting_player = public_state["current_player_id"]
        if acting_player is None:
            break

        player_state = game.get_public_state(match.match_id, viewer_id=acting_player)
        action, amount = choose_action(player_state)

        if amount is None:
            print(f"Decision: {acting_player} chooses to {action}.")
        else:
            print(f"Decision: {acting_player} chooses to {action} {amount} chips.")

        await game.submit_action(
            match_id=match.match_id,
            player_id=acting_player,
            action=action,
            amount=amount,
            turn_id=player_state["turn_id"],
        )

        action_counter += 1

    final_state = game.get_public_state(match.match_id)
    logs = game.get_logs(match.match_id)

    print("\n" + "-" * 60)
    print("Hand complete")
    print(f"- Final status: {final_state['status']}")
    print(f"- Finished on street: {final_state['street']}")
    print(f"- Final board: {human_cards(final_state['board'])}")
    print("- Final stacks:")
    for player in final_state.get("players", []):
        print(f"  * {player['id']}: {player['stack']} chips")
    print(f"- Total engine events logged: {len(logs)}")
    if logs:
        last_event = logs[-1]
        print(
            f"- Last event in log: {last_event['type']} "
            f"(timestamp={last_event['timestamp']:.2f})"
        )

    if final_state["status"] != "finished":
        raise RuntimeError("Demo did not reach showdown/finish state")


if __name__ == "__main__":
    asyncio.run(run_demo_hand())
