# Running an event: organiser notes

How to run a bot tournament on any Wi-Fi, eduroam included. Everything below runs on **your** laptop (the server machine) from the repo root.

## Why there's a tunnel

eduroam blocks connections between devices, so people's bots can't reach `http://<your-laptop-ip>:8000`. A Cloudflare quick tunnel gives the server a public `https://….trycloudflare.com` URL, using only outbound HTTPS. It's free and needs no account. Bots switch to `wss://` automatically.

## Cheat sheet

```bash
./scripts/event.sh up         # start server + tunnel → prints URL + signup command
./scripts/event.sh url        # re-print the URL (warns if it's dead)
./scripts/event.sh newurl     # tunnel died → fresh URL; keys + games survive
./scripts/event.sh key NAME   # hand someone a key manually (saved to .env, survives restarts)
./scripts/event.sh rehearse   # 10 fake bots play a tournament through the tunnel
./scripts/event.sh reset      # restart server: wipes tournament + self-registered keys
./scripts/event.sh logs       # follow server logs
./scripts/event.sh down       # stop everything
```

Admin commands below talk to `localhost:8000`, so they work even if the tunnel is down. Set this once per terminal:

```bash
ADMIN="Authorization: Bearer $(grep '^POKER_ADMIN_API_KEY=' .env | cut -d= -f2-)"
```

## One-time setup

1. Install and start Docker Desktop.
2. `python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt && pip install -e .`
3. `cp exampleenv .env`, then change the admin key in **both** places, or anyone who reads the README can run your tournament:
   ```
   POKER_ADMIN_API_KEY=<something-secret>
   ADMIN_API_KEYS=admin:<same-secret>
   ```
   Leave `REGISTRATION_CODE=` empty; `up` generates one.

## Day before: rehearse

```bash
./scripts/event.sh up
source venv/bin/activate && ./scripts/event.sh rehearse   # expect "status: finished  champion: …"
./scripts/event.sh reset                                    # clear the fake device-* bots
```

Try it **on eduroam** if you can. If `up` never prints a URL, eduroam is blocking Cloudflare, so run the server laptop off a phone hotspot instead. Players can stay on eduroam either way.

## On the day

**1. Start (about 30s)**
```bash
./scripts/event.sh up
```
It prints the URL and a ready-made `curl` signup command containing the join code.

**2. Put this on the projector** (fill in from the `up` output). Share [`joining-the-competition.md`](joining-the-competition.md) with players ahead of time.

> **Get your key** (pick a team name: letters, digits, `-`, `_`):
> ```
> curl -X POST https://<url>/v1/register -H 'Content-Type: application/json' \
>   -d '{"player_id": "YOUR-TEAM-NAME", "code": "<code>"}'
> ```
> **Join the tournament:**
> ```
> pip install git+https://github.com/Manchester-AI-Society/poker_bot_infrastructure
> poker-bot my_bot.py --tournament --server-url https://<url> --api-key <your-key>
> ```
> Or in Python: `play_tournament(MyBot(), api_key="<key>", server_url="https://<url>")`

- **Name taken** (`409`): pick another name.
- **Wrong code** (`403`): check the code on the screen.
- **Someone can't run curl:** run `./scripts/event.sh key their-name` and give them the key it prints.

**3. Watch people join**
```bash
curl localhost:8000/v1/lobby          # bots currently connected and waiting
```
Only bots that are **connected when you start** get seats. Wait until the lobby looks complete. Capacity is 10 tables, each holding up to `MAX_PLAYERS_PER_TABLE` (set in `game/game_service_core.py`).

**4. Start the tournament**
```bash
curl -X POST localhost:8000/v1/tournament/start -H "$ADMIN" -H "Content-Type: application/json" \
  -d '{"starting_stack": 1000, "small_blind": 10, "big_blind": 20, "turn_timeout_seconds": 15, "blind_increase_every_hands": 10, "max_hands": 500}'
```
- **Round 1:** players are split across up to 10 tables that play in parallel until one bot holds all the chips.
- **Final:** the table winners play one final table, and its winner is the champion.
- Blinds double every `blind_increase_every_hands` hands. If `max_hands` is reached, the chip leader advances.

**5. Follow it**
```bash
curl -s localhost:8000/v1/tournament | python3 -m json.tool   # bracket, table winners, champion
./scripts/event.sh logs                                         # live server log
```

**6. Afterwards**
```bash
./scripts/event.sh down
```

## When things go wrong

| Problem | What to do |
|---|---|
| A bot crashed or disconnected mid-game | Leave it. The turn timer auto-checks or auto-folds for it. |
| Players say the URL stopped working | Cloudflare sometimes drops quick tunnels (log says `Tunnel not found`) and cloudflared never recovers by itself. Run `./scripts/event.sh newurl` and put the new URL on screen. Keys, the lobby and running games survive; bots must be restarted with the new `--server-url`. |
| Your own laptop can't open a brand-new URL but phones can | macOS cached a "not found" from before the hostname existed. Wait a few minutes or run `sudo killall -HUP mDNSResponder`. |
| You need to restart the server (`reset`) | Self-registered keys are **wiped**: everyone re-runs the signup curl (their name is free again). Keys from `event.sh key` survive. The URL stays the same. |
| `up` never prints a URL | Network blocks Cloudflare. Use a phone hotspot for your laptop. |
| Someone's key gets `401` | Check it with `curl https://<url>/v1/me -H "Authorization: Bearer <key>"`. If the server restarted, they re-register. |
| Strangers registering | They'd need the join code. To rotate it, delete the `REGISTRATION_CODE=` value in `.env` and run `./scripts/event.sh up` again. |

## Where things live

| Thing | Location |
|---|---|
| Server + tunnel containers | `docker-compose.yml` (tunnel = `tunnel` profile) |
| Event commands | `scripts/event.sh` |
| Keys, admin key, join code | `.env` (never commit it) |
| Self-signup endpoint | `POST /v1/register`, in `server/api/routers/bot_registry_routes.py` |
| Rehearsal script | `examples/bots/remote/simulate_devices.py` (logs in `sim_logs/`) |
