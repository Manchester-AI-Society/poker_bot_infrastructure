# Poker Bot Infrastructure

## Project Title & Overview
`poker_bot_infrastructure` is an authoritative no limits Texas Hold'em poker match server.

It lets you:
- create and start poker matches,
- receive turn events in real time,
- submit legal player actions,
- inspect match state and logs,
- run admin operations through a standalone Python SDK.

The server is authoritative, which means game rules and state transitions are validated on the server, not trusted from clients.

## Short Description
This project runs multiplayer poker games for bots or client applications. It manages cards, blinds, betting rounds, turn order, timeouts, and showdown settlement, then exposes all of this through HTTP and WebSocket APIs.

## Game Logic / How It Works

### Core Rules and Mechanics
- Game type: no-limit Texas Hold'em style hand flow.
- Minimum players per match: 2.
- Blinds: small blind and big blind are posted automatically at hand start.
- Streets: `preflop -> flop -> turn -> river -> showdown`.
- Legal actions are validated per turn:
	- `fold`
	- `check` (only when no chips are needed to call)
	- `call`
	- `bet` (when no current bet exists)
	- `raise_to` (raise to a total target amount)
- Turn timeout: if a player does not act in time, the server auto-submits `check` when possible, otherwise `fold`.

### Gameplay Flow (Step by Step)
1. An admin creates a match with player IDs and blind/stack settings.
2. The server creates a runtime and deals two hole cards per player.
3. Small blind and big blind are posted automatically.
4. The server emits whose turn it is, including legal actions and raise bounds.
5. Players submit actions via HTTP or WebSocket.
6. The action engine validates and applies each action, updating pot, call amount, and action history.
7. When all pending actions are settled for a street, the game advances to the next street and reveals board cards.
8. The process repeats until only one player remains (others folded) or showdown is reached.
9. Showdown evaluates best hands and pays out the pot.

### Win/Loss and Payout Conditions
- Fold win: if all but one player fold, the remaining player wins the entire pot.
- Showdown win: best evaluated hand wins.
- Ties: pot is split equally across tied winners; any chip remainder is distributed one chip at a time to winners by ranking order.
- Match status changes to `finished` after payout.

## Project Structure / How to Read the Code

### High-Level Layout
- `server/`: FastAPI app, route handlers, auth helpers, websocket connection manager.
- `game/`: core poker runtime, rule enforcement, action validation, state projection.
- `admin_sdk/`: standalone Python SDK for admin automation over HTTP.
- `example_scripts/`: runnable scripts that demonstrate match creation and lifecycle flows.

### Where the Game Logic Lives
Core game behaviour is in `game/`. If you are new to the codebase, start here in this order:
1. `game/game_service_core.py`
2. `game/runtime_flow.py`
3. `game/action_engine.py`
4. `game/showdown_resolver.py`
5. `game/poker_game.py`

### Key Modules and Responsibilities
- `game/game_service_core.py`
	- `GameService`: orchestrates match lifecycle (`create`, `start`, `submit_action`, `pause`, `resume`, `end`), logging, and event dispatch.
- `game/match_runtime.py`
	- `MatchRuntime`: in-memory state container for one active match.
- `game/poker_game.py`
	- `pokerGame`: hand engine (blinds, dealing, street progression, per-street action state).
- `game/action_engine.py`
	- `ActionEngine`: legal action calculation and action application (`bet`, `call`, `raise_to`, etc.).
- `game/runtime_flow.py`
	- `RuntimeFlowCoordinator`: turn event preparation, street advancement, showdown trigger logic.
- `game/showdown_resolver.py`
	- `ShowdownResolver`: fold-win and showdown payout settlement.
- `game/state_projection.py`
	- `StateProjection`: builds public and admin state payloads for API responses.
- `game/turn_timeout_manager.py`
	- `TurnTimeoutManager`: schedules and handles per-turn timeouts.
- `server/api/fastapi_application.py`
	- creates FastAPI app and wires routers.
- `server/api/routers/`
	- HTTP and WebSocket endpoints.
- `admin_sdk/admin_client.py`
	- `AdminSDKClient`: Python client wrapper for admin API calls.

## How to Run the Project

### 1. Prerequisites
- Python 3.11+
- `pip`

### 2. Set Up Environment
From repository root:

```bash
source venv/bin/activate
```

If you prefer creating a new environment instead:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Install Dependencies
```bash
python -m pip install -r requirements.txt
```

### 4. Configure Environment Variables
Create `.env` from the provided sample:

```bash
cp exampleenv .env
```

Important variables:
- `POKER_SERVER_URL` (for SDK/scripts)
- `POKER_ADMIN_API_KEY`
- `ADMIN_API_KEYS` (`id:key` pairs)
- `BOT_API_KEYS` (`id:key` pairs)
- `POKER_ADMIN_TIMEOUT_SECONDS`

### 5. Start the Server
```bash
uvicorn server.run_poker_server:app --reload --host 0.0.0.0 --port 8000
```

Health check:

```bash
curl http://127.0.0.1:8000/health
```

## How to Play / Run a Game

### Option A: Run an Example Script (Fastest)
Scripts auto-start the server if needed.

```bash
python example_scripts/create_one_game_with_api_key.py
python example_scripts/create_multiple_games_with_api_keys.py
python example_scripts/mock_poker_bot_game_announce_winner.py
```

### Option B: Manual API Flow (Step by Step)

1. Create a match (admin key required):

```bash
curl -X POST http://127.0.0.1:8000/v1/matches \
	-H "X-Admin-Key: admin-dev-key" \
	-H "Content-Type: application/json" \
	-d '{
		"player_ids": ["dev-bot-1", "dev-bot-2"],
		"starting_stack": 1000,
		"small_blind": 10,
		"big_blind": 20,
		"turn_timeout_seconds": 15,
		"event_log_limit": 2000
	}'
```

2. Start the match:

```bash
curl -X POST http://127.0.0.1:8000/v1/matches/<MATCH_ID>/start \
	-H "X-Admin-Key: admin-dev-key"
```

3. Fetch state for a player (shows legal actions for that player when it is their turn):

```bash
curl "http://127.0.0.1:8000/v1/matches/<MATCH_ID>?viewer_id=dev-bot-1"
```

4. Submit an authenticated player action:

```bash
curl -X POST http://127.0.0.1:8000/v1/matches/<MATCH_ID>/actions/self \
	-H "X-API-Key: dev-key-1" \
	-H "Content-Type: application/json" \
	-d '{"action": "check", "turn_id": 1}'
```

Example raise:

```bash
curl -X POST http://127.0.0.1:8000/v1/matches/<MATCH_ID>/actions/self \
	-H "X-API-Key: dev-key-1" \
	-H "Content-Type: application/json" \
	-d '{"action": "raise_to", "amount": 60, "turn_id": 3}'
```

5. Read event history:

```bash
curl "http://127.0.0.1:8000/v1/matches/<MATCH_ID>/events?offset=0&limit=100"
```

### Optional: Real-Time Play with WebSocket
- Endpoint: `ws://127.0.0.1:8000/v1/ws`
- Authenticate with `Authorization: Bearer <api_key>` or `?api_key=<api_key>`.
- Send action messages like:

```json
{
	"type": "action",
	"match_id": "<MATCH_ID>",
	"turn_id": 2,
	"action": "check"
}
```
