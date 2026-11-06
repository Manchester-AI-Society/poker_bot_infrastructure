# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

The venv lives in `venv/` (not `.venv`): `source venv/bin/activate`.

```bash
pip install -r requirements.txt && pip install -e ".[dev]"   # setup
cp exampleenv .env                                            # dev keys

uvicorn server.run_poker_server:app --reload --port 8000      # run server
docker compose up --build -d                                  # or containerised

pytest                                  # all tests (integration ones auto-start a server on :8000)
pytest -m "not integration"             # fast unit suite
pytest tests/test_tournament.py::TestSplitting -v               # single class/test

ruff check . && ruff format --check .   # what CI runs (also: python -m compileall)
```

CI (`.github/workflows/ci.yml`) runs **only** ruff lint, `ruff format --check`, and a compile check. It does not run pytest, so run the tests locally. Line length is 79.

Integration tests and `player_sdk.testing.play_local_match` reuse whatever server already answers on `POKER_SERVER_URL` (default `127.0.0.1:8000`), including a running Docker container, and only spawn uvicorn if none is up.

## Architecture

Three layers with a strict dependency direction: **SDKs → HTTP/WS → server → game**. `game/` has no knowledge of FastAPI or sockets.

**`game/`: authoritative engine, pure asyncio.**
- `GameService` (`game_service_core.py`) owns every `MatchRuntime`.
- Each runtime holds an `asyncio.Lock`. Every mutation (`submit_action`, start, pause, end) runs under it.
- Side effects leave through callbacks that the server injects (`set_event_handlers`: broadcast, direct send, connected check; `set_match_ended_handler`). This is how the engine stays transport-free.
- `action_engine`: legality and raise bounds. `bet` and `raise_to` both mean "make my street total X" and are normalised by whether a bet already stands.
- `runtime_flow`: turn and street progression. `showdown_resolver`: payouts. `turn_timeout_manager`: auto check/fold.
- `state_projection.build_public_state`: per-viewer redaction (only your own hole cards).
- **Turn ids:** every turn carries a `turn_id`. Actions with a stale id are rejected. A rejected action does **not** cancel the turn timer.
- **Readiness gate:** `start_match` only arms a match. Dealing begins when every player's websocket is connected (`on_player_connected`), unless `force` or `wait_for_players=False`.
- `tournament.py`: two-round knockout layered on `GameService`.
  - Round 1 splits the lobby across `min(10, n // 2)` tables, each capped at `MAX_PLAYERS_PER_TABLE = 23` (deck limit).
  - Table winners play a final table.
  - It advances through the match-ended callback. One tournament per process, held in memory.

**`server/`: FastAPI adapter.**
- `server/api/shared_runtime_dependencies.py` builds the process-wide singletons: `api_keys` (key → player_id), `admin_api_keys`, `ConnectionManager`, `GameService`, `Tournament`. It wires their callbacks together and holds the auth helpers.
- Routers in `server/api/routers/` are thin.
- **All state is in memory.** Keys come from `BOT_API_KEYS` / `ADMIN_API_KEYS` env vars (format `id:key,id:key`; the dev keys in `server_settings.py` apply when unset). Keys added at runtime through `/v1/admin/players` or `/v1/register` are lost on restart.
- `POST /v1/register` is self-service signup. It is disabled unless `REGISTRATION_CODE` is set.
- `/v1/ws` is the realtime gateway. Bots receive `your_turn`, `action`, `showdown`, `match_ended`, and in tournaments `table_assigned` / `eliminated` / `tournament_ended`.

**`player_sdk/`: the only package installed by `pip install` (`poker-player-sdk`).**
- Bots subclass `PokerBot` and implement `act(GameState) -> Action`. `Action` has only `fold` / `call` / `raise_to`.
- `client.translate_action` maps these to the engine's names: call → check when free, raise → bet when no bet stands.
- Entry points: `play()` (single match, all args mandatory, ignores env), `play_tournament()`, and the `poker-bot` CLI (`_run.py`, resolves `POKER_*` env vars and `.env`).
- `_ws.RealtimeBotRunner` is the websocket transport. It reconnects, recovers missed turns over HTTP, and falls back to HTTP polling in `auto` mode. An `https` server URL becomes `wss`.
- `player_sdk/testing` is for local harnesses. It needs the repo checkout, because it launches `server/`.

**`admin_sdk/`:** a sync HTTP client for match lifecycle, player keys, lobby and tournament.

## Events and networking

- `docker-compose.yml` has a `tunnel` profile: a Cloudflare quick tunnel that gives a public `https://*.trycloudflare.com` URL over outbound TCP 443. It exists because eduroam blocks device-to-device traffic.
- `scripts/event.sh` wraps the operations: `up`, `url`, `newurl`, `key`, `rehearse`, `reset`, `logs`, `down`.
- Quick tunnels can die (`Tunnel not found` in the logs) and never self-heal. `newurl` recreates only the tunnel container.
- `examples/bots/remote/simulate_devices.py` rehearses a tournament with N separate bot processes.
- Operator runbook: `docs/running-an-event.md`. Participant guide: `docs/joining-the-competition.md`. Keep both in sync with behaviour changes to registration, the CLI, or the tournament.

## Conventions

- Examples bootstrap `sys.path` themselves (E402 is ignored there), so run them from the repo root as plain scripts.
- Deliberate simplifications are marked with `# ponytail:` comments that name the limit and the upgrade path.
- The websocket protocol pairs the server and SDK from the same checkout. Change both together.
