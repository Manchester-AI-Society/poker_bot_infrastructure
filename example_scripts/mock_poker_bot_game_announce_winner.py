import json
import os
from pathlib import Path
import sys
import time
from typing import Dict, List
from urllib import error, request

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from admin_sdk import AdminSDKClient, AdminSDKConfiguration
from admin_sdk.models import MatchCreationOptions
from example_scripts.server_autostart import ensure_server_running


def _http_json(
    method: str,
    url: str,
    payload: Dict | None,
    headers: Dict[str, str] | None,
) -> Dict:
    """Sends an HTTP request and parses the JSON response.

    Args:
        method (str): HTTP method value.
        url (str): Target URL.
        payload (Dict | None): Optional JSON payload.
        headers (Dict[str, str] | None): Optional HTTP headers.

    Returns:
        Dict: Parsed JSON response mapping.
    """
    body = None
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")

    request_headers = {"Accept": "application/json"}
    if body is not None:
        request_headers["Content-Type"] = "application/json"
    if headers:
        request_headers.update(headers)

    req = request.Request(
        url=url,
        data=body,
        method=method.upper(),
        headers=request_headers,
    )

    try:
        with request.urlopen(req, timeout=10.0) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except error.HTTPError as exc:
        message = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {message}") from exc


def _parse_player_keys() -> Dict[str, str]:
    """Builds a player-to-key mapping from environment configuration.

    Args:
        None: This function does not take external arguments.

    Returns:
        Dict[str, str]: Mapping from player identifier to API key.
    """
    raw = os.getenv(
        "BOT_API_KEYS",
        "dev-bot-1:dev-key-1,dev-bot-2:dev-key-2,dev-bot-3:dev-key-3",
    )
    mapping: Dict[str, str] = {}
    chunks = [chunk.strip() for chunk in raw.split(",") if chunk.strip()]
    for chunk in chunks:
        if ":" not in chunk:
            continue
        player_id, api_key = chunk.split(":", 1)
        player_id = player_id.strip()
        api_key = api_key.strip()
        if player_id and api_key:
            mapping[player_id] = api_key
    return mapping


def _choose_action(legal_actions: List[str]) -> str:
    """Chooses a simple mock action from legal actions.

    Args:
        legal_actions (List[str]): Collection of currently legal actions.

    Returns:
        str: Chosen action value.
    """
    for action in ["check", "call", "fold", "raise_to", "bet"]:
        if action in legal_actions:
            return action
    return "fold"


def main() -> None:
    """Runs a mock bot game and announces the winner.

    print("[example] Loading Admin SDK configuration from environment...")
    Args:
        None: This function does not take external arguments.

    print(f"[example] Using server URL: {base_url}")

    print("[example] Parsing bot API keys from BOT_API_KEYS...")
    Returns:
        None: This function does not return a value.
    """
    configuration = AdminSDKConfiguration.from_environment()
    ensure_server_running(configuration.base_url)
    client = AdminSDKClient(configuration)
    base_url = configuration.base_url.rstrip("/")

    print("[example] Creating mock match...")
    player_keys = _parse_player_keys()

    required_players = ["dev-bot-1", "dev-bot-2"]
    for player_id in required_players:
        if player_id not in player_keys:
            raise RuntimeError(f"Missing API key for player {player_id}")

    created = client.create_match(
        MatchCreationOptions(
            player_ids=required_players,
            number_of_bots_allowed=2,
            starting_stack=1000,
            small_blind=10,
            big_blind=20,
            turn_timeout_seconds=8,
            event_log_limit=2000,
            table_label="mock-bot-table",
            tournament_round="demo",
        )
    )
    match_id = created["match_id"]
    print(f"[example] Match created: {match_id}")

    print("[example] Starting mock match...")
    client.start_match(match_id)
    print("[example] Running mock bot loop...")

    deadline = time.time() + 120
    while time.time() < deadline:
        full_state = client.get_full_match_state(match_id)["state"]
        status = full_state["status"]
        if status == "finished":
            print("[example] Match finished naturally.")
            break

        current_player_id = full_state.get("current_player_id")
        if not current_player_id:
            time.sleep(0.2)
            continue

        state_payload = _http_json(
            "GET",
            f"{base_url}/v1/matches/{match_id}?viewer_id={current_player_id}",
            None,
            None,
        )
        state = state_payload.get("state", {})
        legal_actions = state.get("legal_actions", [])
        chosen_action = _choose_action(legal_actions)
        print(
            f"[example] {current_player_id} legal={legal_actions} -> action={chosen_action}"
        )

        action_payload = {"action": chosen_action}
        if chosen_action == "raise_to":
            action_payload["amount"] = 40
        if chosen_action == "bet":
            action_payload["amount"] = 20

        _http_json(
            "POST",
            f"{base_url}/v1/matches/{match_id}/actions/self",
            action_payload,
            {"X-API-Key": player_keys[current_player_id]},
        )
        time.sleep(0.1)
    else:
        print("[example] Match timed out in demo loop; ending via admin command...")
        client.end_match(
            match_id,
            api_key_being_used=configuration.admin_api_key,
        )

    final_state = client.get_full_match_state(match_id)["state"]
    players = final_state.get("players", [])
    if not players:
        raise RuntimeError("No players found in final state")

    winner = max(players, key=lambda player: int(player.get("stack", 0)))
    print("[example] Winner announced.")
    print(
        {
            "match_id": match_id,
            "winner": winner.get("id"),
            "winning_stack": winner.get("stack"),
            "final_status": final_state.get("status"),
        }
    )


if __name__ == "__main__":
    main()
