# Poker bot competition

Write a Python poker bot. On the day it connects to the organiser's server over
the internet and plays a no-limit Texas Hold'em knockout against everyone
else's bots. The server deals the cards and enforces the rules; your bot only
decides what to do each turn. Your bot runs **on your own computer**, so any
library, model or file you have is fine.

If you cannot connect, there is a backup: hand your bot in as a zip file and the
organiser plays it for you (see "If you cannot connect").

## How the event works

* **Round 1.** Everyone connected when the organiser starts is shuffled onto
  tables of up to 23 bots. Every table plays at the same time, until one bot
  holds all the chips on its table.
* **The final.** The winner of each table plays at the final table. The winner of
  the final is the champion.
* **Blinds go up.** They double every few hands, so waiting for perfect cards
  loses. If a table reaches its hand limit, the bot with the most chips goes
  through.
* **Only bots in the lobby at the start get a seat.** Connect early and leave
  your bot running.
* **The event website** shows the play a few minutes behind the real game, with
  your cards shown only when a hand reaches a showdown. Its Info page has the
  server address, the join code, the timeline and the prize.

## 1. Set up

You need Python 3.11 or newer and git.

```bash
git clone https://github.com/Manchester-AI-Society/poker_bot_infrastructure.git
cd poker_bot_infrastructure
python -m venv venv
venv\Scripts\activate          # macOS and Linux: source venv/bin/activate
python -m pip install -r requirements.txt
python -m pip install -e .
```

Check that it works. This should print `OK: played 40 hands vs @call with no faults`:

```bash
python -m arena validate bots/starter
```

## 2. Write your bot

`bots/starter` is the template. Copy it and keep your bot in its own folder:

```bash
cp -r bots/starter bots/myteam      # PowerShell: Copy-Item -Recurse bots\starter bots\myteam
```

Your bot is `bots/myteam/bot.py` with **exactly one** class that extends
`PokerBot`. Its `act(game_state)` method is called each time it is your turn and
must return a `Response`:

| Response | Meaning |
|---|---|
| `Response.fold()` | Give up the hand. |
| `Response.call()` | Call, or check when nothing is owed. |
| `Response.raise_to(total)` | Bet or raise. `total` is the total chips you want in this betting round, between `game_state.min_raise_to` and `game_state.max_raise_to`. |
| `Response.all_in()` | Put in everything you have left. |

If your bot crashes, returns something that is not a `Response`, or raises by an
illegal amount, it is **not** knocked out: a safe move is played (check, or fold
if you are facing a bet) and the reason is printed in your terminal.

What `game_state` holds (the details that are easy to guess wrong):

| | |
|---|---|
| **Cards** | Two-character strings: rank then suit, both upper case, with `T` for ten: `AS`, `TD`, `7H`, `2C`. Suits are `S`, `H`, `D`, `C`. |
| **pot_size** | The chips in the middle right now, including bets already made this round. |
| **call_amount** | The chips you must add to stay in. Zero means you can check. |
| **min_raise_to, max_raise_to** | The smallest and largest total you may give to `Response.raise_to`. `max_raise_to` is all-in. |
| **legal_actions** | The moves you may make, from `fold`, `check`, `call`, `bet`, `raise_to`. `Response.call()` covers both `call` and `check`. |
| **my_stack, my_bet** | The chips you have left, and what you have put in this round. |
| **stack_sizes, current_bets, folded, all_in** | Everyone at the table, by seat; `my_index` is your seat. |
| **action_history** | This hand so far. Each record has `player_id`, `action`, `amount` and `street`. |

The docstring at the top of `bots/starter/bot.py` explains the rest.

## 3. Test it on your computer

```bash
python -m arena validate bots/myteam
python -m arena match bots/myteam call --deals 200
```

`validate` checks that your bot loads and plays legally. `match` plays it against
a built-in opponent (`call`, `fold`, `random` or `shove`) or against another bot
folder, and prints how many big blinds per hand it won. If it shows `faults:`
above zero, the first fault and its reason are printed.

## 4. Join the event

When the event opens, the **Info** page of the event website shows the server
address and the join code.

**Get your key.** Pick a team name (letters, digits, `-` and `_`) and run one of
these, putting in the server address and the join code:

```powershell
Invoke-RestMethod -Method Post SERVER_URL/v1/register -ContentType 'application/json' -Body '{"player_id":"YOUR-TEAM-NAME","code":"JOIN-CODE"}'
```

```bash
curl -X POST SERVER_URL/v1/register -H 'Content-Type: application/json' -d '{"player_id": "YOUR-TEAM-NAME", "code": "JOIN-CODE"}'
```

You get back an `api_key`. **Save it**: it cannot be looked up again.

**Connect your bot** and leave it running:

```bash
python -m player_sdk bots/myteam/bot.py --tournament --server-url SERVER_URL --api-key YOUR_KEY
```

You should see `Playing as YOUR-TEAM-NAME (websocket)` and `Waiting in the
tournament lobby`. When the organiser starts the event your terminal shows each
hand and ends with `Eliminated in round N` or `Tournament over; champion: ...`.
If your connection drops, run the same command again; it picks up where it was.

## If you cannot connect

If you cannot get a connection (a blocked network, a laptop problem), hand your
bot in as a file instead. Websockets come first: the backup is used only if you
are **not** connected when the event starts.

```bash
python -m arena pack bots/myteam --team myteam
```

That checks your bot and writes `myteam.zip`. Upload it in the backup form (the
link is on the Info page). You can upload again: the newest zip that works is the
one used. Use the same team name everywhere. A backup bot runs on the
organiser's machine, so keep it small: the Python standard library and what
`requirements.txt` installs, CPU only, at most 25 MB.

## The rules

* **Be quick.** Every turn has a time limit (about 15 seconds). If it runs out,
  the server checks for you, or folds if checking is not allowed. Load models and
  files when your bot starts, not inside `act`.
* **Illegal or broken answers** cost you the turn (a safe move is played), never
  your seat.
* **One bot per team.**
* **Fair play.** Do not attack the server, the website, or other teams'
  connections, and do not try to find out other teams' cards.

## If something goes wrong

| What you see | What to do |
|---|---|
| `Invalid API key` or `401` | A typo in the key, or the server was restarted. Register again (the same name is free again after a restart). |
| `403` when registering | The join code is wrong. Check it on the Info page. |
| `409` when registering | That team name is taken. Pick another. |
| `Could not reach server` | Use the address exactly as shown (it starts with `https://`, with no `:8000`). Open `SERVER_URL/health` in a browser: `{"ok":true}` means the server is up. |
| `Expected exactly one PokerBot subclass` | Keep only one `PokerBot` class in your file, with no constructor arguments. |
| The terminal says a safe move was played | Your bot crashed or answered illegally; the message says why. Fix it and run the same command again. |
| Your bot keeps folding or checking without your code running | `act` is too slow, so the turn timer acted for you. |

## For the organiser

`scripts/event.ps1` runs a live event from a Windows laptop with no Docker
(`up`, `status`, `url`, `backups`, `start`, `down`): the poker server, a
Cloudflare tunnel and the live site feed. It needs `cloudflared.exe` in `tools\`.
The Home page text is `event.json`. The operator runbook and the architecture
notes are on the `try/ammar-websockets` branch (`ORGANISER.md`, `ARCHITECTURE.md`).

This project is licensed under the [MIT License](LICENSE).
