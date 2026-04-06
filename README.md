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

3. Optionally configure bot API keys:

```bash
export BOT_API_KEYS="bot1:key1,bot2:key2"
```

If `BOT_API_KEYS` is not set, default keys are:

- `dev-key-1` -> `dev-bot-1`
- `dev-key-2` -> `dev-bot-2`
- `dev-key-3` -> `dev-bot-3`

4. Run the server:

```bash
uvicorn server.run_poker_server:app --reload --host 0.0.0.0 --port 8000
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