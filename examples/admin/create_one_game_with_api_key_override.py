import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from admin_sdk import AdminSDKClient, AdminSDKConfiguration
from admin_sdk.models import MatchCreationOptions
from player_sdk.testing import ensure_server_running


def main() -> None:
    """Creates one game using a per-request admin API key override.

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

    print("[example] Creating match with explicit key override...")
    created = client.create_match(
        MatchCreationOptions(
            player_ids=["dev-bot-1", "dev-bot-2"],
            number_of_bots_allowed=2,
            starting_stack=1200,
            small_blind=10,
            big_blind=20,
            turn_timeout_seconds=15,
            event_log_limit=2000,
        ),
        api_key_being_used=configuration.admin_api_key,
    )

    print("[example] Starting match with explicit key override...")
    started = client.start_match(
        created["match_id"],
        api_key_being_used=configuration.admin_api_key,
    )

    print("[example] Completed API-key-override flow.")
    print({"created": created, "started": started})


if __name__ == "__main__":
    main()
