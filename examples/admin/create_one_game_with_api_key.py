import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from admin_sdk import AdminSDKClient, AdminSDKConfiguration
from admin_sdk.models import MatchCreationOptions
from player_sdk.testing import ensure_server_running


def main() -> None:
    """Creates and starts one game with an admin API key.

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

    print("[example] Creating a single match with admin API key...")
    created = client.create_match(
        MatchCreationOptions(
            player_ids=["dev-bot-1", "dev-bot-2"],
            number_of_bots_allowed=2,
            starting_stack=1000,
            small_blind=10,
            big_blind=20,
            turn_timeout_seconds=15,
            event_log_limit=2000,
        )
    )
    match_id = created["match_id"]
    print(f"[example] Match created: {match_id}")

    print("[example] Starting the match...")
    started = client.start_match(match_id)

    print("[example] Completed single-game flow.")
    print({"created": created, "started": started})


if __name__ == "__main__":
    main()
