import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from admin_sdk import AdminSDKClient, AdminSDKConfiguration
from admin_sdk.exceptions import AdminSDKAuthenticationError
from admin_sdk.models import MatchCreationOptions
from player_sdk.testing import ensure_server_running


def main() -> None:
    """Shows a failed admin operation when no API key is provided.

    Args:
        None: This function does not take external arguments.

    Returns:
        None: This function does not return a value.
    """
    print("[example] Loading Admin SDK configuration from environment...")
    configuration = AdminSDKConfiguration.from_environment()
    ensure_server_running(configuration.base_url)
    print("[example] Building client with an empty admin API key...")
    client = AdminSDKClient(
        AdminSDKConfiguration(
            base_url=configuration.base_url,
            admin_api_key="",
            timeout_seconds=configuration.timeout_seconds,
        )
    )

    print("[example] Attempting to create a match without admin API key...")
    try:
        client.create_match(
            MatchCreationOptions(
                player_ids=["dev-bot-1", "dev-bot-2"],
                number_of_bots_allowed=2,
            )
        )
    except AdminSDKAuthenticationError as error:
        print("[example] Received expected authentication failure.")
        print({"expected_auth_failure": str(error)})
        return

    raise RuntimeError("Expected authentication failure did not happen")


if __name__ == "__main__":
    main()
