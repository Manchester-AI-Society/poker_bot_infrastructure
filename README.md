# poker_bot_infrastructure

This repository contains a Python server for running poker matches with FastAPI, WebSocket messaging, and uvicorn.

The server is authoritative: game rules, game state, and state transitions are enforced on the server.

## Server Quick Start

1. Activate the existing virtual environment:

```bash
source venv/bin/activate
```

2. Install dependencies:

```bash
python -m pip install -r server/requirements.txt
```

3. Configure environment values in `.env` at the repository root.

You can copy the sample values from `exampleenv`:

```bash
cp exampleenv .env
```

4. Run the server (optional if you use example scripts):

```bash
uvicorn server.run_poker_server:app --reload --host 0.0.0.0 --port 8000
```

The app loads `.env` automatically via `python-dotenv` in both SDK and server startup.

### Environment Variables

Bot keys and admin keys are configured as comma-separated `id:key` pairs.

- `BOT_API_KEYS` example: `dev-bot-1:dev-key-1,dev-bot-2:dev-key-2`
- `ADMIN_API_KEYS` example: `admin:admin-dev-key`
- `POKER_SERVER_URL` example: `http://127.0.0.1:8000`
- `POKER_ADMIN_API_KEY` example: `admin-dev-key`
- `POKER_ADMIN_TIMEOUT_SECONDS` example: `10`

If `BOT_API_KEYS` is not set, default keys are:

- `dev-key-1` -> `dev-bot-1`
- `dev-key-2` -> `dev-bot-2`
- `dev-key-3` -> `dev-bot-3`

## Example Scripts

Scripts in `example_scripts/` now auto-start the server if it is not running.
This means you can run them directly without opening a second terminal.

### Run One Game (Admin Key Override)

```bash
python example_scripts/create_one_game_with_api_key_override.py
```

### Run One Game (Admin Key from Config)

```bash
python example_scripts/create_one_game_with_api_key.py
```

### Run Multiple Games

```bash
python example_scripts/create_multiple_games_with_api_keys.py
```

### Validate Missing Admin Key Behavior

```bash
python example_scripts/create_one_game_without_api_key.py
```

### Run Mock Bot Game and Announce Winner

```bash
python example_scripts/mock_poker_bot_game_announce_winner.py
```

### Optional: override bot API keys in shell

```bash
export BOT_API_KEYS="bot1:key1,bot2:key2"
```

### Optional: override admin API keys in shell

```bash
export ADMIN_API_KEYS="admin:admin-dev-key"
```

## HTTP API

- `GET /health`
- `GET /v1/bots`
- `GET /v1/matches`
- `POST /v1/matches`
- `POST /v1/matches/{match_id}/start`
- `GET /v1/matches/{match_id}`
- `GET /v1/matches/{match_id}/events`
- `POST /v1/matches/{match_id}/actions`
- `POST /v1/matches/{match_id}/actions/self`
- `POST /v1/matches/{match_id}/pause` (admin)
- `POST /v1/matches/{match_id}/resume` (admin)
- `POST /v1/matches/{match_id}/end` (admin)
- `GET /v1/matches/{match_id}/full-state` (admin)
- `GET /v1/matches/{match_id}/admin-actions` (admin)
- `POST /v1/admin/players` (admin)
- `GET /v1/admin/players` (admin)
- `DELETE /v1/admin/players/{player_id}` (admin)
- `POST /v1/admin/players/{player_id}/rotate-key` (admin)

### Create Match Example

```bash
curl -X POST http://localhost:8000/v1/matches \
	-H "Content-Type: application/json" \
	-d '{
		"player_ids": ["dev-bot-1", "dev-bot-2"],
		"starting_stack": 1000,
		"small_blind": 10,
		"big_blind": 20,
		"turn_timeout_seconds": 15
	}'
```

### Start Match Example

```bash
curl -X POST http://localhost:8000/v1/matches/<MATCH_ID>/start
```

## WebSocket API

Endpoint:

- `ws://localhost:8000/v1/ws`

Authentication:

- `Authorization: Bearer <api_key>` header, or
- `?api_key=<api_key>` query param

Client action message:

```json
{
	"type": "action",
	"match_id": "abc123",
	"turn_id": 2,
	"action": "check"
}
```

Server events:

- `connected`
- `your_turn`
- `action`
- `showdown`
- `timeout`
- `error`

## Running Multiple Matches Concurrently

You can run multiple poker matches at the same time on a single server instance.

How this works:

- Each match has a unique `match_id` and separate state.
- Players submit actions with a `match_id`, so actions are routed to the correct match.
- Match mutations are guarded by a per-match lock, so two matches can progress independently.

Typical flow:

1. Create several matches with `POST /v1/matches`.
2. Start each one with `POST /v1/matches/{match_id}/start`.
3. Have bots submit actions against the specific `match_id` they are playing.

## Admin SDK (Standalone)

The admin SDK is separated from server code in its own root folder:

- `admin_sdk/`

This keeps admin automation independent from server internals. The SDK talks to the server over HTTP only.

### Admin SDK Quick Start

```python
from admin_sdk import AdminSDKClient, AdminSDKConfiguration
from admin_sdk.models import EndMatchOptions, MatchCreationOptions

config = AdminSDKConfiguration(
	base_url="http://127.0.0.1:8000",
	admin_api_key="admin-dev-key",
)
client = AdminSDKClient(config)

create_result = client.create_match(
	MatchCreationOptions(
		player_ids=["dev-bot-1", "dev-bot-2"],
		number_of_bots_allowed=2,
		starting_stack=1000,
		small_blind=10,
		big_blind=20,
		turn_timeout_seconds=15,
		event_log_limit=2000,
	),
)
match_id = create_result["match_id"]

client.start_match(match_id)
client.pause_match(match_id, reason="manual review")
client.resume_match(match_id, reason="review completed")
client.end_match(match_id, EndMatchOptions(reason="admin stop", mode="terminate_as_is"))
```

### Required Admin Options

The admin SDK supports the required options:

1. `number_of_bots_allowed`
2. `api_key_being_used` (optional per-call override when invoking SDK methods)

### Suggested Admin-Only Controls

The following controls are implemented or recommended for admin use only:

1. Match lifecycle commands: start, pause, resume, end.
2. Full private state inspection with all hole cards.
3. Player provisioning and API key lifecycle management.
4. Admin action history for operational audits.
5. End modes:
- `terminate_as_is`
- `refund_committed`
