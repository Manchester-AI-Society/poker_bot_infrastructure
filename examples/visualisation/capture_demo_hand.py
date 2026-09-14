"""Captures a real poker hand as frame data for the demo GIF.

Runs three demo bots against each other on a local server (started
automatically when needed), snapshots the omniscient admin state after
every event batch so all hole cards are visible, and writes the best
captured hand to ``docs/demo_hand.json`` for ``render_demo_gif.py``.

Usage:
    python examples/visualisation/capture_demo_hand.py
    python examples/visualisation/capture_demo_hand.py --attempts 8
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple
from urllib.parse import quote
from uuid import uuid4

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from admin_sdk import AdminSDKClient, AdminSDKConfiguration
from admin_sdk.models import MatchCreationOptions
from player_sdk._http import PlayerSDKBadRequestError, http_json
from player_sdk.bot_interface import PokerBot
from player_sdk.client import translate_action
from player_sdk.models import Action, GameState
from player_sdk.parser import GameStateParser
from player_sdk.testing.local_server import ensure_server_running

SIGNIFICANT_EVENT_TYPES = ("action", "street_advanced", "showdown")

_FRAME_EVENT_KEYS = (
    "type",
    "player_id",
    "action",
    "amount",
    "street",
    "pot",
    "board",
    "results",
)


class DemoBot(PokerBot):
    """Loose-passive bot that sprinkles in raises so demo hands run deep."""

    def __init__(self, seed: int) -> None:
        """Initialises the bot with a deterministic random stream."""
        self._rng = random.Random(seed)

    def act(self, game_state: GameState) -> Action:
        """Calls modest prices and occasionally raises a little more."""
        rng = self._rng
        target = game_state.min_raise_to or 0
        can_aggress = game_state.can_bet or game_state.can_raise
        if can_aggress and target:
            ceiling = min(game_state.max_raise_to or target, target + 80)
            if rng.random() < 0.25 and target <= ceiling:
                amount = min(ceiling, target + 20 * rng.randrange(0, 4))
                return Action.raise_to(int(amount))
        if game_state.call_amount <= 220:
            return Action.call()
        return Action.fold()


def _build_frame(
    full_state: Mapping[str, Any], events: List[Mapping[str, Any]]
) -> Dict[str, Any]:
    """Converts an admin state snapshot plus its events into a frame."""
    significant = [
        {key: event[key] for key in _FRAME_EVENT_KEYS if key in event}
        for event in events
        if event.get("type") in SIGNIFICANT_EVENT_TYPES
    ]
    players = [
        {
            "id": seat["id"],
            "stack": seat["stack"],
            "bet": seat["bet"],
            "folded": seat["folded"],
            "all_in": seat["all_in"],
            "hole_cards": list(seat.get("hole_cards") or []),
        }
        for seat in full_state.get("players", [])
    ]
    return {
        "street": full_state.get("street"),
        "board": list(full_state.get("board") or []),
        "pot": full_state.get("pot", 0),
        "status": full_state.get("status"),
        "acting_index": full_state.get("acting_index"),
        "players": players,
        "events": significant,
    }


def _act_for_player(
    base_url: str,
    match_id: str,
    player_id: str,
    api_key: str,
    bot: PokerBot,
    parser: GameStateParser,
) -> None:
    """Fetches the viewer state and submits the bot's chosen action."""
    viewer_query = f"viewer_id={quote(player_id)}"
    payload = http_json(
        base_url, "GET", f"/v1/matches/{match_id}?{viewer_query}"
    )
    state_payload = payload.get("state", {})
    legal_actions = state_payload.get("legal_actions") or []
    if not legal_actions:
        return

    players = state_payload.get("players", [])
    hero_index = next(
        (
            index
            for index, player in enumerate(players)
            if isinstance(player, Mapping) and player.get("id") == player_id
        ),
        None,
    )
    game_state = parser.parse(payload, hero_index=hero_index)

    action = bot.act(game_state)
    engine_action, amount = translate_action(action, game_state)
    body: Dict[str, Any] = {"action": engine_action}
    if amount is not None:
        body["amount"] = int(amount)
    if game_state.turn_id is not None:
        body["turn_id"] = game_state.turn_id

    try:
        http_json(
            base_url,
            "POST",
            f"/v1/matches/{match_id}/actions/self",
            payload=body,
            headers={"X-API-Key": api_key},
        )
    except PlayerSDKBadRequestError:
        pass


def _synthesise_blind_events(
    state: Mapping[str, Any], small_blind: int, big_blind: int
) -> List[Dict[str, Any]]:
    """Rebuilds the opening blind events from the initial posted bets.

    Blind posts are broadcast but not written to the server event log,
    so they are recreated here from the first state snapshot.
    """
    events: List[Dict[str, Any]] = [{"type": "hand_started"}]
    for seat in state.get("players", []):
        bet = seat.get("bet")
        if bet == small_blind:
            events.append(
                {
                    "type": "action",
                    "action": "post_small_blind",
                    "player_id": seat["id"],
                    "amount": bet,
                }
            )
        elif bet == big_blind:
            events.append(
                {
                    "type": "action",
                    "action": "post_big_blind",
                    "player_id": seat["id"],
                    "amount": bet,
                }
            )
    return events


def _capture_hand(
    admin: AdminSDKClient,
    base_url: str,
    bots: Dict[str, PokerBot],
    player_keys: Dict[str, str],
    match_id: str,
    *,
    small_blind: int,
    big_blind: int,
    poll_interval_seconds: float = 0.05,
    max_duration_seconds: float = 90.0,
) -> List[Dict[str, Any]]:
    """Drives a match to completion, recording a frame per event batch."""
    frames: List[Dict[str, Any]] = []
    events_seen = 0
    parser = GameStateParser()
    deadline = time.monotonic() + max_duration_seconds

    initial_state = admin.get_full_match_state(match_id).get("state", {})
    frames.append(
        _build_frame(
            initial_state,
            _synthesise_blind_events(initial_state, small_blind, big_blind),
        )
    )

    while time.monotonic() < deadline:
        page = http_json(
            base_url,
            "GET",
            f"/v1/matches/{match_id}/events?offset={events_seen}&limit=100",
        )
        events = page.get("events") or []
        if events:
            events_seen += len(events)
            if any(
                event.get("type") in SIGNIFICANT_EVENT_TYPES
                for event in events
            ):
                full_state = admin.get_full_match_state(match_id).get(
                    "state", {}
                )
                frames.append(_build_frame(full_state, events))

        state = http_json(base_url, "GET", f"/v1/matches/{match_id}").get(
            "state", {}
        )
        if state.get("status") == "finished":
            break

        current_player_id = state.get("current_player_id")
        bot = bots.get(current_player_id)
        if bot is None:
            time.sleep(poll_interval_seconds)
            continue

        _act_for_player(
            base_url,
            match_id,
            current_player_id,
            player_keys[current_player_id],
            bot,
            parser,
        )
        time.sleep(poll_interval_seconds)

    return frames


def _run_match(
    admin: AdminSDKClient,
    base_url: str,
    seed: int,
    *,
    starting_stack: int,
    small_blind: int,
    big_blind: int,
) -> Tuple[str, List[str], List[Dict[str, Any]]]:
    """Registers players, runs one match, and returns its captured frames."""
    prefix = f"demo-{uuid4().hex[:6]}"
    player_ids = [f"{prefix}-{index}" for index in (1, 2, 3)]

    bots: Dict[str, PokerBot] = {}
    player_keys: Dict[str, str] = {}
    for index, player_id in enumerate(player_ids):
        created = admin.create_player(player_id)
        api_key = created.get("api_key")
        if not created.get("created") or not api_key:
            raise RuntimeError(
                f"Could not register player '{player_id}' on the server"
            )
        bots[player_id] = DemoBot(seed * 100 + index)
        player_keys[player_id] = api_key

    match_id = admin.create_match(
        MatchCreationOptions(
            player_ids=player_ids,
            number_of_bots_allowed=len(player_ids),
            starting_stack=starting_stack,
            small_blind=small_blind,
            big_blind=big_blind,
            turn_timeout_seconds=12,
            event_log_limit=500,
        )
    )["match_id"]
    admin.start_match(match_id)

    frames = _capture_hand(
        admin,
        base_url,
        bots,
        player_keys,
        match_id,
        small_blind=small_blind,
        big_blind=big_blind,
    )
    return match_id, player_ids, frames


def _blind_ids(
    frames: List[Dict[str, Any]],
) -> Tuple[Optional[str], Optional[str]]:
    """Finds the small and big blind player ids from the captured events."""
    sb_id: Optional[str] = None
    bb_id: Optional[str] = None
    for frame in frames:
        for event in frame["events"]:
            action = event.get("action")
            if action == "post_small_blind" and sb_id is None:
                sb_id = event.get("player_id")
            elif action == "post_big_blind" and bb_id is None:
                bb_id = event.get("player_id")
    return sb_id, bb_id


def _is_interesting(frames: List[Dict[str, Any]]) -> bool:
    """Checks whether a hand reached a real showdown with some aggression."""
    showdown_events = [
        event
        for frame in frames
        for event in frame["events"]
        if event.get("type") == "showdown"
    ]
    if not showdown_events:
        return False

    results = showdown_events[-1].get("results") or []
    reached_showdown = any(
        result.get("hand") not in ("Won by Fold", "Folded")
        for result in results
    )
    aggressive_actions = sum(
        1
        for frame in frames
        for event in frame["events"]
        if event.get("type") == "action"
        and event.get("action") in ("bet", "raise_to")
    )
    return reached_showdown and aggressive_actions >= 2


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Capture a demo poker hand as frame data."
    )
    parser.add_argument("--attempts", type=int, default=6)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--starting-stack", type=int, default=1000)
    parser.add_argument("--small-blind", type=int, default=10)
    parser.add_argument("--big-blind", type=int, default=20)
    parser.add_argument("--output", default="docs/demo_hand.json")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    base_url = args.base_url.rstrip("/")
    output_path = Path(args.output)
    if not output_path.is_absolute():
        output_path = PROJECT_ROOT / output_path

    ensure_server_running(base_url)
    admin_key = os.getenv("POKER_ADMIN_API_KEY", "").strip() or "admin-dev-key"
    admin = AdminSDKClient(
        AdminSDKConfiguration(base_url=base_url, admin_api_key=admin_key)
    )

    chosen: Optional[Tuple[str, List[str], List[Dict[str, Any]]]] = None
    for attempt in range(1, args.attempts + 1):
        seed = args.seed * 1000 + attempt
        match_id, player_ids, frames = _run_match(
            admin,
            base_url,
            seed,
            starting_stack=args.starting_stack,
            small_blind=args.small_blind,
            big_blind=args.big_blind,
        )
        print(
            f"[capture] attempt {attempt}/{args.attempts}: match"
            f" {match_id}, {len(frames)} frames"
        )
        if _is_interesting(frames):
            chosen = (match_id, player_ids, frames)
            break

    if chosen is None:
        print("[capture] no interesting hand captured; try raising --attempts")
        return 1

    match_id, player_ids, frames = chosen
    sb_id, bb_id = _blind_ids(frames)
    dealer_index = 0
    if len(player_ids) == 3 and sb_id and bb_id:
        dealer_index = next(
            index
            for index, player_id in enumerate(player_ids)
            if player_id not in (sb_id, bb_id)
        )

    payload = {
        "meta": {
            "match_id": match_id,
            "player_ids": player_ids,
            "starting_stack": args.starting_stack,
            "small_blind": args.small_blind,
            "big_blind": args.big_blind,
            "sb_id": sb_id,
            "bb_id": bb_id,
            "dealer_index": dealer_index,
            "captured_at": datetime.now(timezone.utc).isoformat(),
        },
        "frames": frames,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2))
    print(f"[capture] wrote {len(frames)} frames to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
