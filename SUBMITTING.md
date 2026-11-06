# How to enter your bot

You write a Python poker bot. On the day it connects to the organiser's server
over the internet and plays a no-limit Texas Hold'em knockout tournament against
everyone else's bots. The server deals the cards and enforces the rules. Your
bot only decides what to do each turn. Your bot runs **on your own computer**,
so any library, model or file you have is fine.

If you cannot connect, there is a backup: you can hand your bot in as a file and
the organiser plays it for you (see "If you cannot connect").

## How the event works

* **Round 1.** Everyone who is connected when the organiser starts the event is
  shuffled onto tables of up to 23 bots. Every table plays at the same time, until
  one bot holds all the chips on its table.
* **The final.** The winner of each table plays at the final table. The winner
  of the final is the champion.
* **Blinds go up.** They double every few hands (the organiser sets how often),
  so waiting for perfect cards loses. If a table reaches its hand limit, the bot
  with the most chips goes through.
* **Only bots in the lobby at the start get a seat.** Connect early and leave
  your bot running.
* **This website** shows the play as it happens, but on purpose a few minutes
  behind the real game, and it shows your cards only when a hand reaches a
  showdown.

## 1. Set up

You need Python 3.11 or newer and a copy of this project:

```bash
git clone https://github.com/Manchester-AI-Society/poker_bot_infrastructure.git
cd poker_bot_infrastructure
python -m venv venv
venv\Scripts\activate          # macOS and Linux: source venv/bin/activate
python -m pip install -r requirements.txt
python -m pip install -e .
```

## 2. Write your bot

Start from the starter bot and keep your bot in its own folder:

```bash
cp -r bots/starter bots/myteam      # PowerShell: Copy-Item -Recurse bots\starter bots\myteam
```

Your bot is `bots/myteam/bot.py` with **exactly one** class that extends
`PokerBot`. Its `act(game_state)` method is called each time it is your turn and
must return a `Response`:

* `Response.fold()` gives up the hand.
* `Response.call()` calls, or checks when nothing is owed.
* `Response.raise_to(total)` bets or raises. `total` is the total number of chips
  you want to have in this betting round, between `game_state.min_raise_to` and
  `game_state.max_raise_to`.
* `Response.all_in()` puts in everything you have left.

If your bot crashes, returns something that is not a `Response`, or raises by an
illegal amount, your bot is **not** knocked out: a safe move is played (check, or
fold if you are facing a bet) and the reason is printed in your terminal, so you
can fix it.

### What your bot is given

`act(game_state)` receives a `GameState`. These are the details that are easy to
guess wrong:

| | |
|---|---|
| **Cards** | Two-character strings: rank then suit, both upper case, with `T` for ten: `AS`, `TD`, `7H`, `2C`. The suits are `S`, `H`, `D`, `C`. |
| **pot_size** | The chips in the middle right now, including bets already made this round. |
| **call_amount** | The chips you must add to stay in. Zero means you can check. |
| **min_raise_to, max_raise_to** | The smallest and largest total you may give to `Response.raise_to`. `max_raise_to` is all-in. |
| **legal_actions** | Only the moves you may make, from `fold`, `check`, `call`, `bet`, `raise_to`. `Response.call()` covers both `call` and `check`. |
| **my_stack, my_bet** | The chips you have left, and what you have put in this round. |
| **stack_sizes, current_bets, folded, all_in** | Everyone at the table, by seat; `my_index` is your seat. |
| **action_history** | This hand so far. Each record has `player_id`, `action`, `amount` and `street`. |

## 3. Test it on your computer

```bash
python -m arena validate bots/myteam
python -m arena match bots/myteam call --deals 200
```

`validate` checks that your bot loads and plays legally. `match` plays it against
a simple built-in opponent (`call`, `fold`, `random` or `shove`) or against another
bot folder, and prints how many big blinds per hand it won. If it shows `faults:`
above zero, the first fault and its reason are printed.

You can also play a few hands against a copy of the real server, with no tunnel
or internet needed:

```python
# test_my_bot.py
from bots.myteam.bot import MyBot          # use your class name
from examples.bots.conservative_bot import ExampleConservativeBot
from player_sdk.testing import play_local_match

result = play_local_match([MyBot(), ExampleConservativeBot()], max_hands=50)
print(result.winner_id, result.final_stacks)
```

## 4. Join the event

When the event opens, the **Connect now** box at the top of this page shows the
server address and the join code (or says to ask the organiser for the code).

**Get your key.** Pick a team name (letters, digits, `-` and `_`) and run one of
these, putting in the server address and the join code:

```powershell
Invoke-RestMethod -Method Post SERVER_URL/v1/register -ContentType 'application/json' -Body '{"player_id":"YOUR-TEAM-NAME","code":"JOIN-CODE"}'
```

```bash
curl -X POST SERVER_URL/v1/register -H 'Content-Type: application/json' -d '{"player_id": "YOUR-TEAM-NAME", "code": "JOIN-CODE"}'
```

You get back an `api_key`. **Save it**: it is yours and cannot be looked up again.

**Connect your bot** and leave it running:

```bash
python -m player_sdk bots/myteam/bot.py --tournament --server-url SERVER_URL --api-key YOUR_KEY
```

You should see `Playing as YOUR-TEAM-NAME (websocket)` and `Waiting in the
tournament lobby`. When the organiser starts the event your terminal shows each
hand and ends with `Eliminated in round N` or `Tournament over; champion: ...`.
If your connection drops, start the same command again; it picks up where it was.

## If you cannot connect

If you cannot get a connection (a blocked network, a laptop problem), hand your
bot in as a file instead and the organiser plays it for you. Websockets come
first: this backup is used only if you are **not** connected when the event
starts.

```bash
python -m arena pack bots/myteam --team myteam
```

That checks your bot and writes `myteam.zip`. Upload it in the **backup form**
(the link is in the Connect now box). You can upload again: the newest zip that
works is the one that is used. Use the same team name everywhere.

## The rules

* **Be quick.** Every turn has a time limit (about 15 seconds, set by the
  organiser). If it runs out, the server checks for you, or folds if checking is
  not allowed. Load models and files when your bot starts, not inside `act`.
* **Illegal or broken answers** cost you the turn (a safe move is played), never
  your seat.
* **One bot per team.** Your bot may use any library and any hardware you have.
* **Fair play.** Do not attack the server, the website, or other teams'
  connections, and do not try to find out other teams' cards.

## If something goes wrong

| What you see | What to do |
|---|---|
| `Invalid API key` or `401` | A typo in the key, or the server was restarted. Register again (the same name is free again after a restart). |
| `403` when registering | The join code is wrong. Check it in the Connect now box. |
| `409` when registering | That team name is taken. Pick another. |
| `Could not reach server` | Use the address exactly as shown (it starts with `https://`, with no `:8000`). Open `SERVER_URL/health` in a browser: `{"ok":true}` means the server is up. |
| `Expected exactly one PokerBot subclass` | Keep only one `PokerBot` class in your file, with no constructor arguments. |
| The terminal says a safe move was played | Your bot crashed or answered illegally; the message says why. Fix it and run the same command again. |
| Your bot keeps folding or checking without your code running | `act` is too slow, so the turn timer acted for you. |
| This website shows nothing yet | The stream is a few minutes behind the real game on purpose, and updates every few minutes. |
