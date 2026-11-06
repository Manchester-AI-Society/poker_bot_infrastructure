# Poker bot competition

A no-limit Texas Hold'em knockout for Python bots. You write a bot, test it on
your own computer, and on the day it connects to the organiser's server over
the internet (a websocket) and plays everyone else's bot. If you cannot
connect, you hand your bot in as a zip file and the organiser plays it for you.

* **Round 1.** Everyone connected when the organiser starts is shuffled onto
  tables of up to 23 bots. Tables play at the same time until one bot holds all
  the chips on its table.
* **The final.** The winner of each table plays at the final table. Blinds
  double every few hands, so waiting for perfect cards loses. If a table
  reaches its hand limit, the bot with the most chips goes through.
* **The website** shows the play as it happens, a few minutes behind the real
  game on purpose, with your cards shown only when a hand reaches a showdown.
  Its Info page has the server address, the join code and everything else a
  team needs.

Start with [SUBMITTING.md](SUBMITTING.md): it is the full competitor guide,
from setting up to joining the event.

## What you need

* Python 3.11 or newer.
* Git.
* This repository.
* A network connection that can reach the organiser's server on the day. Your
  bot runs on your own computer, so any library or model you have is fine. If
  you cannot connect, use the zip backup below.

## Set up

```bash
git clone https://github.com/Manchester-AI-Society/poker_bot_infrastructure.git
cd poker_bot_infrastructure
python -m venv .venv
```

Activate the environment (Windows PowerShell: `.venv\Scripts\Activate.ps1`,
macOS and Linux: `source .venv/bin/activate`), then install the requirements:

```bash
python -m pip install -r requirements.txt
```

Check that it works. This should print `OK: played 40 hands vs @call with no faults`:

```bash
python -m arena validate bots/starter
```

## Write a bot

Copy the starter bot. Your bot is the folder you copy; it needs a `bot.py` with
exactly one class that extends `PokerBot`.

```bash
cp -r bots/starter bots/myteam
```

On Windows PowerShell use `Copy-Item -Recurse bots\starter bots\myteam`.

Your `act(game_state)` method is called each time it is your turn. It must
return a `Response`:

| Response | Meaning |
|---|---|
| `Response.fold()` | Give up the hand. |
| `Response.call()` | Call, or check when nothing is owed. |
| `Response.raise_to(total)` | Bet or raise. `total` is the total chips you want in this betting round, between `game_state.min_raise_to` and `game_state.max_raise_to`. |
| `Response.all_in()` | Put in everything you have left. |

Anything else, or an illegal amount, is a mistake (see the rules below). The
starter bot explains what information `game_state` holds, and
[SUBMITTING.md](SUBMITTING.md) has a table of the details that are easy to get
wrong. `bots/starter` is the template to copy ([bots/README.md](bots/README.md)).

## Test it locally

```bash
python -m arena validate bots/myteam
python -m arena match bots/myteam call --deals 200
python -m arena match bots/myteam random --deals 300
```

`validate` checks that your bot loads and plays legally. `match` plays your bot
against a built-in opponent (`call`, `fold`, `random`, `shove`) or against
another bot folder, with the same engine and scoring as the competition. If a
match shows `faults:` above zero, the first fault is printed with its reason (for
example `raise_to(1) is outside the allowed range: the total must be between 40
and 2000 chips`). `validate` prints it too. The folder `arena_logs/` holds what
your bot printed, any crash output, and a line for each illegal response.

## Join the live event

When the event opens, the website's Info page shows the server address and the
join code. Register a team name to get a key, then connect your bot and leave it
running:

```bash
python -m player_sdk bots/myteam/bot.py --tournament --server-url SERVER_URL --api-key YOUR_KEY
```

[SUBMITTING.md](SUBMITTING.md) has the register command for PowerShell and
`curl`, what to expect in the terminal, and a troubleshooting table. If your
connection drops, run the same command again.

## The backup: hand your bot in as a zip

Websockets come first. If you cannot get a connection (a blocked network, a
laptop problem), pack your bot and upload it in the backup form (the link is on
the Info page):

```bash
python -m arena pack bots/myteam --team myteam
```

This checks your bot again and writes `myteam.zip`. The organiser plays it on
their own machine as an ordinary websocket client, **only if your team is not
connected live when the event starts**. You can upload again: the newest zip
that works is the one used. Use the same team name everywhere (lowercase
letters, digits, `-` and `_`, up to 32 characters).

## The rules

| | |
|---|---|
| **Time** | Every turn has a time limit (about 15 seconds, set by the organiser). If it runs out, the server checks for you, or folds if checking is not allowed. Load models and files when your bot starts, not inside `act`. |
| **Mistakes** | An exception, an illegal move, or a return value that is not a `Response` costs you the turn, never your seat: a safe move is played (check, otherwise fold) and the reason is printed in your terminal. |
| **One bot per team** | Any library and any hardware you have. In the zip backup the bot runs on the organiser's machine, so keep it small: the Python standard library and what `requirements.txt` installs, CPU only, at most 25 MB. |
| **Fair play** | Do not attack the server, the website, or other teams' connections, and do not try to find out other teams' cards. |

## More

* [SUBMITTING.md](SUBMITTING.md): the full competitor guide (also on the website).
* [bots/README.md](bots/README.md): the bot template and how to use it.
* [ORGANISER.md](ORGANISER.md): how the live event is run (for the organiser).
* [docs/running-an-event.md](docs/running-an-event.md): the Docker version of the
  event runbook.
* [ARCHITECTURE.md](ARCHITECTURE.md): how it works inside.
* [docs/legacy-server.md](docs/legacy-server.md): the match server and SDK in
  detail.

This project is licensed under the [MIT License](LICENSE).
