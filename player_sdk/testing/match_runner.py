from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Dict, List, Mapping, Optional, Sequence, Tuple, Union
from uuid import uuid4

from .._http import PlayerSDKBadRequestError, http_json
from ..bot_interface import PokerBot
from ..client import translate_action
from ..models import Action
from ..parser import GameStateParser

BotSpec = Union[PokerBot, type]


@dataclass(frozen=True)
class MatchResult:
    """Outcome summary for a completed local match."""

    match_id: str
    status: str
    winner_id: Optional[str] = None
    winning_stack: Optional[int] = None
    final_stacks: Dict[str, int] = field(default_factory=dict)


def play_local_match(
    bots: Union[Sequence[BotSpec], Mapping[str, BotSpec]],
    *,
    base_url: str = "http://127.0.0.1:8000",
    admin_api_key: Optional[str] = None,
    starting_stack: int = 1000,
    small_blind: int = 10,
    big_blind: int = 20,
    turn_timeout_seconds: int = 15,
    event_log_limit: int = 2000,
    start_server: bool = True,
    poll_interval_seconds: float = 0.1,
    max_duration_seconds: float = 300.0,
    verbose: bool = True,
) -> MatchResult:
    """Plays a full match between bots on a local server.

    Starts a server when needed, registers each bot as a player with
    a fresh API key, creates and starts a match, then drives every
    turn until the match finishes (or the duration limit is hit, in
    which case the match is ended by admin command).

    Args:
        bots: Bots (instances or no-arg classes); a mapping provides
            explicit player ids, otherwise ids are generated.
        base_url (str): Server base URL.
        admin_api_key (Optional[str]): Admin key; falls back to
            POKER_ADMIN_API_KEY then the dev default.
        starting_stack (int): Chips per player.
        small_blind (int): Small blind size.
        big_blind (int): Big blind size.
        turn_timeout_seconds (int): Per-turn timeout.
        event_log_limit (int): Server event log capacity.
        start_server (bool): Auto-start uvicorn when unreachable.
        poll_interval_seconds (float): Delay between state polls.
        max_duration_seconds (float): Hard wall-clock limit.
        verbose (bool): Prints progress when True.

    Returns:
        MatchResult: Match outcome including winner and final stacks.
    """
    from admin_sdk import AdminSDKClient, AdminSDKConfiguration
    from admin_sdk.models import MatchCreationOptions

    from .local_server import ensure_server_running

    named_bots = _normalise_bots(bots)
    if len(named_bots) < 2:
        raise ValueError("At least two bots are required to play a match")

    base_url = base_url.rstrip("/")
    if start_server:
        ensure_server_running(base_url)

    admin_key = (
        admin_api_key
        or os.getenv("POKER_ADMIN_API_KEY", "").strip()
        or "admin-dev-key"
    )
    admin = AdminSDKClient(
        AdminSDKConfiguration(base_url=base_url, admin_api_key=admin_key)
    )

    player_keys: Dict[str, str] = {}
    for player_id, _ in named_bots:
        created = admin.create_player(player_id)
        api_key = created.get("api_key")
        if not created.get("created") or not api_key:
            raise RuntimeError(
                f"Player id '{player_id}' is already registered on the"
                " server; pass unique player ids for each local match."
            )
        player_keys[player_id] = api_key

    match_id = admin.create_match(
        MatchCreationOptions(
            player_ids=[player_id for player_id, _ in named_bots],
            number_of_bots_allowed=len(named_bots),
            starting_stack=starting_stack,
            small_blind=small_blind,
            big_blind=big_blind,
            turn_timeout_seconds=turn_timeout_seconds,
            event_log_limit=event_log_limit,
        )
    )["match_id"]
    admin.start_match(match_id)
    if verbose:
        print(f"[player_sdk] Match {match_id} started:")
        print(
            f"[player_sdk]   players="
            f"{[player_id for player_id, _ in named_bots]}"
        )

    bots_by_id = {player_id: bot for player_id, bot in named_bots}
    parser = GameStateParser()
    deadline = time.monotonic() + max_duration_seconds
    timed_out = False

    while time.monotonic() < deadline:
        state_payload = http_json(base_url, "GET", f"/v1/matches/{match_id}")
        state = state_payload.get("state", {})
        if state.get("status") == "finished":
            break

        current_player_id = state.get("current_player_id")
        bot = bots_by_id.get(current_player_id)
        if bot is None:
            time.sleep(max(0.0, poll_interval_seconds))
            continue

        act_for_player(
            base_url,
            match_id,
            current_player_id,
            player_keys[current_player_id],
            bot,
            parser,
        )
        time.sleep(max(0.0, poll_interval_seconds))
    else:
        timed_out = True

    if timed_out:
        if verbose:
            print("[player_sdk] Duration limit reached; ending match...")
        admin.end_match(match_id)

    state = http_json(base_url, "GET", f"/v1/matches/{match_id}").get(
        "state", {}
    )

    return _build_result(match_id, state, verbose=verbose)


def act_for_player(
    base_url: str,
    match_id: str,
    player_id: str,
    api_key: str,
    bot: PokerBot,
    parser: GameStateParser,
) -> None:
    """Fetches the viewer state and submits the bot's chosen action.

    Silently skips stale or superseded turns (e.g. when a timeout was
    already applied server-side).
    """
    from urllib.parse import quote

    viewer_query = f"viewer_id={quote(player_id)}"
    viewer_payload = http_json(
        base_url, "GET", f"/v1/matches/{match_id}?{viewer_query}"
    )
    state_payload = viewer_payload.get("state", {})
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
    game_state = parser.parse(viewer_payload, hero_index=hero_index)

    action = bot.act(game_state)
    if not isinstance(action, Action):
        raise TypeError("PokerBot.act must return an Action")

    engine_action, amount = translate_action(action, game_state)
    body: Dict[str, object] = {"action": engine_action}
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
        # Stale or superseded turn (e.g. timeout already applied); skip.
        pass


def _normalise_bots(
    bots: Union[Sequence[BotSpec], Mapping[str, BotSpec]],
) -> List[Tuple[str, PokerBot]]:
    if isinstance(bots, Mapping):
        items = list(bots.items())
    else:
        prefix = f"local-bot-{uuid4().hex[:6]}"
        items = [
            (f"{prefix}-{index}", bot)
            for index, bot in enumerate(bots, start=1)
        ]

    normalised: List[Tuple[str, PokerBot]] = []
    for player_id, bot in items:
        if isinstance(bot, type):
            bot = bot()
        if not isinstance(bot, PokerBot):
            raise TypeError(
                f"{player_id} is not a PokerBot instance or subclass"
            )
        normalised.append((player_id, bot))
    return normalised


def _build_result(
    match_id: str, state: Mapping[str, object], *, verbose: bool
) -> MatchResult:
    players = state.get("players") or []
    stacks: Dict[str, int] = {}
    for player in players:
        if isinstance(player, Mapping):
            stacks[str(player.get("id"))] = int(player.get("stack", 0))

    winner_id: Optional[str] = None
    winning_stack: Optional[int] = None
    if stacks:
        winner_id, winning_stack = max(
            stacks.items(), key=lambda item: item[1]
        )

    result = MatchResult(
        match_id=match_id,
        status=str(state.get("status", "unknown")),
        winner_id=winner_id,
        winning_stack=winning_stack,
        final_stacks=stacks,
    )
    if verbose:
        print(f"[player_sdk] Match {match_id} finished:")
        print(
            {
                "winner": result.winner_id,
                "winning_stack": result.winning_stack,
                "final_stacks": result.final_stacks,
                "status": result.status,
            }
        )
    return result
