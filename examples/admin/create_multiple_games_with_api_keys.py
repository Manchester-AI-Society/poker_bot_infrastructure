import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from admin_sdk import AdminSDKClient, AdminSDKConfiguration
from admin_sdk.models import MatchCreationOptions
from player_sdk.testing import ensure_server_running

PAIRINGS = [
    ["dev-bot-1", "dev-bot-2"],
    ["dev-bot-2", "dev-bot-3"],
    ["dev-bot-1", "dev-bot-3"],
]


def main() -> None:
    """Creates and starts multiple games with admin API keys.

    Args:
        None: This function does not take external arguments.

    Returns:
        None: This function does not return a value.
    """
    print("[example] Loading Admin SDK configuration from environment...")
    configuration = AdminSDKConfiguration.from_environment()
    ensure_server_running(configuration.base_url)
    client = AdminSDKClient(configuration)
    print(f"[example] Using server URL: {configuration.base_url}")
    print(f"[example] Creating {len(PAIRINGS)} matches...")

    created_matches = []
    for index, player_ids in enumerate(PAIRINGS, start=1):
        print(f"[example] Creating match {index} with players: {player_ids}")
        created = client.create_match(
            MatchCreationOptions(
                player_ids=player_ids,
                number_of_bots_allowed=len(player_ids),
                starting_stack=1000,
                small_blind=10,
                big_blind=20,
                turn_timeout_seconds=15,
                event_log_limit=2000,
            )
        )
        match_id = created["match_id"]
        print(f"[example] Starting match {index}: {match_id}")
        started = client.start_match(match_id)
        created_matches.append({"created": created, "started": started})

    print("[example] Completed multi-game flow.")
    print({"matches": created_matches})


if __name__ == "__main__":
    main()
