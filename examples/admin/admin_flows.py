"""Admin SDK example flows: match creation, key overrides, and auth failures.

Usage:
    python examples/admin/admin_flows.py single
    python examples/admin/admin_flows.py single --key-override
    python examples/admin/admin_flows.py multi
    python examples/admin/admin_flows.py no-key
"""

import argparse
import sys
from pathlib import Path
from typing import List, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from admin_sdk import AdminSDKClient, AdminSDKConfiguration
from admin_sdk.exceptions import AdminSDKAuthenticationError
from admin_sdk.models import MatchCreationOptions
from player_sdk.testing import ensure_server_running

MULTI_MATCH_PAIRINGS = [
    ["dev-bot-1", "dev-bot-2"],
    ["dev-bot-2", "dev-bot-3"],
    ["dev-bot-1", "dev-bot-3"],
]


def build_client(
    admin_api_key: Optional[str] = None,
) -> tuple[AdminSDKClient, AdminSDKConfiguration]:
    """Loads configuration from the environment and builds a client."""
    print("[example] Loading Admin SDK configuration from environment...")
    configuration = AdminSDKConfiguration.from_environment()
    ensure_server_running(configuration.base_url)
    print(f"[example] Using server URL: {configuration.base_url}")
    if admin_api_key is not None:
        configuration = AdminSDKConfiguration(
            base_url=configuration.base_url,
            admin_api_key=admin_api_key,
            timeout_seconds=configuration.timeout_seconds,
        )
    return AdminSDKClient(configuration), configuration


def create_and_start(
    client: AdminSDKClient,
    player_ids: List[str],
    *,
    starting_stack: int = 1000,
    key_override: Optional[str] = None,
) -> dict:
    """Creates and starts one match, printing progress along the way."""
    overrides = {"api_key_being_used": key_override} if key_override else {}
    created = client.create_match(
        MatchCreationOptions(
            player_ids=player_ids,
            number_of_bots_allowed=len(player_ids),
            starting_stack=starting_stack,
            small_blind=10,
            big_blind=20,
            turn_timeout_seconds=15,
            event_log_limit=2000,
        ),
        **overrides,
    )
    match_id = created["match_id"]
    print(f"[example] Match created: {match_id}")
    print("[example] Starting the match...")
    started = client.start_match(match_id, **overrides)
    return {"created": created, "started": started}


def run_single(args: argparse.Namespace) -> None:
    """Creates and starts one match using the configured admin key."""
    client, configuration = build_client()
    key_override = (
        configuration.admin_api_key if args.key_override else None
    )
    print(
        "[example] Creating a single match"
        + (" with explicit key override..." if key_override else "...")
    )
    result = create_and_start(
        client,
        ["dev-bot-1", "dev-bot-2"],
        starting_stack=args.starting_stack,
        key_override=key_override,
    )
    print("[example] Completed single-game flow.")
    print(result)


def run_multi(args: argparse.Namespace) -> None:
    """Creates and starts several matches for different player pairings."""
    client, _ = build_client()
    print(f"[example] Creating {len(MULTI_MATCH_PAIRINGS)} matches...")
    results = []
    for index, player_ids in enumerate(MULTI_MATCH_PAIRINGS, start=1):
        print(f"[example] Creating match {index} with players: {player_ids}")
        results.append(create_and_start(client, player_ids))
    print("[example] Completed multi-game flow.")
    print({"matches": results})


def run_no_key(args: argparse.Namespace) -> None:
    """Shows a failed admin operation when no API key is provided."""
    print("[example] Building client with an empty admin API key...")
    client, _ = build_client(admin_api_key="")
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


def main() -> None:
    """Parses arguments and dispatches the selected example flow."""
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="flow", required=True)

    single = subparsers.add_parser(
        "single", help="Create and start one match"
    )
    single.add_argument("--starting-stack", type=int, default=1000)
    single.add_argument(
        "--key-override",
        action="store_true",
        help="Pass the admin key explicitly on each request",
    )
    single.set_defaults(func=run_single)

    multi = subparsers.add_parser(
        "multi", help="Create and start several matches"
    )
    multi.set_defaults(func=run_multi)

    no_key = subparsers.add_parser(
        "no-key", help="Demo the expected auth failure without a key"
    )
    no_key.set_defaults(func=run_no_key)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
