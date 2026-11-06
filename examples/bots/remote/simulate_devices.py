"""Rehearse an event: N bots, each in its own process, play a tournament.

Each bot is a separate OS process with its own websocket — the same as
N laptops — so pointing it at the tunnel URL exercises the real path:

    POKER_SERVER_URL=https://<random>.trycloudflare.com \
        python examples/bots/remote/simulate_devices.py --bots 10

Needs POKER_ADMIN_API_KEY (read from .env) to register bots and start.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from admin_sdk import AdminSDKClient, AdminSDKConfiguration

BOT_FILE = PROJECT_ROOT / "examples" / "bots" / "conservative_bot.py"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bots", type=int, default=10)
    args = parser.parse_args()

    config = AdminSDKConfiguration.from_environment()
    admin = AdminSDKClient(config)
    print(f"[sim] server: {config.base_url}")

    stamp = int(time.time())
    keys = {}
    for index in range(args.bots):
        player_id = f"device-{index}-{stamp}"
        keys[player_id] = f"{player_id}-key"
        admin.create_player(player_id, api_key=keys[player_id])

    log_dir = PROJECT_ROOT / "sim_logs"
    log_dir.mkdir(exist_ok=True)
    processes = {
        player_id: subprocess.Popen(
            [
                sys.executable,
                "-m",
                "player_sdk",
                str(BOT_FILE),
                "--tournament",
                "--server-url",
                config.base_url,
                "--api-key",
                key,
            ],
            cwd=PROJECT_ROOT,
            stdout=open(log_dir / f"{player_id}.log", "w"),
            stderr=subprocess.STDOUT,
        )
        for player_id, key in keys.items()
    }

    deadline = time.time() + 60
    while missing := set(keys) - set(admin.get_lobby()["players"]):
        if time.time() > deadline:
            sys.exit(f"[sim] never reached the lobby: {sorted(missing)}")
        time.sleep(0.5)
    print(f"[sim] all {args.bots} bots in the lobby, starting tournament")

    bracket = admin.start_tournament(
        starting_stack=200,
        small_blind=5,
        big_blind=10,
        turn_timeout_seconds=8,
        blind_increase_every_hands=3,
        max_hands=200,
    )
    for table in bracket["tables"]:
        print(f"[sim] round 1 table: {table['player_ids']}")

    failed = {pid: p.wait(timeout=600) for pid, p in processes.items()}
    failed = {pid: code for pid, code in failed.items() if code}

    final = admin.get_tournament()
    print(f"[sim] status: {final['status']}  champion: {final['champion']}")
    print(f"[sim] per-bot logs in {log_dir}")
    if failed or final["status"] != "finished":
        sys.exit(f"[sim] FAILED, non-zero exits: {failed}")


if __name__ == "__main__":
    main()
