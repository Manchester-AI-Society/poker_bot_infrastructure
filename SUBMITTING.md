# How to enter your bot

For competitors. Your bot runs **on your own computer** and plays by connecting
to the organiser's arena over the network. Nobody else ever sees your code, and
anything your bot needs (a model, a GPU, an API key) stays with you.

## How the competition works

There are **two rounds** and no live leaderboard.

* **Round 1, groups.** Every team is drawn at random into a group of at most 8.
  Each group plays a round robin: everyone plays everyone else in the group.
* **Round 2, finals.** The best 2 bots of each group play a round robin among
  themselves. The best finals score wins.

Nothing about how anyone is doing is published while a round is being played.
The group tables appear when Round 1 is complete, and the final table when
Round 2 is.

Every match is a number of **deals** (the organiser says how many). Each deal is
played twice with the two bots swapping seats, so card luck mostly cancels, and
the score is in big blinds per hand with a 95% confidence interval.

## 1. Write your bot

You need a copy of this project to test with:

```bash
git clone https://github.com/Manchester-AI-Society/poker_bot_infrastructure.git
cd poker_bot_infrastructure
python -m venv .venv
.venv\Scripts\Activate.ps1          # macOS/Linux: source .venv/bin/activate
python -m pip install -r requirements.txt
```

Start from the starter bot, or from any example in `bots/` (see
[bots/README.md](bots/README.md)):

```bash
cp -r bots/starter bots/myteam      # PowerShell: Copy-Item -Recurse bots\starter bots\myteam
```

Your bot is one file, `bot.py`, with exactly one `PokerBot` class. Read the top
of `bots/starter/bot.py`: it explains the three things a bot can do (fold, call,
raise) and what information it gets.

### What your bot is given

`act(game_state)` receives a `GameState`. These are the details that are easy
to guess wrong:

| | |
|---|---|
| **Cards** | Two-character strings: rank then suit, both upper case, with `T` for ten: `AS`, `TD`, `7H`, `2C`. The suits are `S`, `H`, `D`, `C`. |
| **pot_size** | The chips in the middle right now, including bets already made this round. At the start of a hand it is 30 (the two blinds). |
| **call_amount** | The chips you must add to stay in. Zero means you can check. |
| **legal_actions** | Only the moves you may make, from `fold`, `check`, `call`, `bet`, `raise_to`. `bet` appears only when nobody has bet this round. |
| **action_history** | This hand so far. Each record has `player_id`, `action`, `amount` and `street`. Actions are `post_small_blind`, `post_big_blind`, `fold`, `check`, `call`, `bet` and `raise_to`. For `call` and `bet` the amount is the chips added; for `raise_to` it is the total you have in this round. |
| **Your class** | Exactly one `PokerBot` subclass, with a constructor that takes no arguments. |

## 2. Test it locally

```bash
python -m arena validate bots/myteam                    # does it load and play legally?
python -m arena match bots/myteam call --deals 200      # against a calling station
python -m arena match bots/myteam bots/equity_calc --deals 300
```

This is the same engine and the same scoring the competition uses. If `validate`
says **OK**, your bot plays legally. If a match shows `faults:` above zero, read
the log in `arena_logs/` (or in the folder you give with `--log-dir`).

## 3. Register and connect to the arena

The organiser tells you the arena's **address** (something like
`ws://192.168.1.20:8765`) and a **join code**. You choose your own **team name**:
lowercase letters, digits, `-` and `_`, up to 32 characters, first come first
served. On your own machine, run:

```bash
python -m arena.connect --url ws://ADDRESS:8765 --team yourteam --code JOINCODE bots/myteam
```

That registers your team, saves your secret key on your computer, and connects
your bot. Every later run only needs your team name:

```bash
python -m arena.connect --url ws://ADDRESS:8765 --team yourteam bots/myteam
```

You should see `connected as team 'yourteam'; waiting for matches`. **Leave it
running for the whole event.** It reconnects by itself if your Wi-Fi drops, and
prints `match starting` and `match finished` as your matches are played.

Registration closes when the organiser draws the groups, so register early. If
the organiser gave you a key instead, use
`python -m arena.connect --url ws://ADDRESS:8765 --key YOUR_KEY bots/myteam`
(or set the `ARENA_KEY` environment variable to keep it off the command line).

* **Your key** is saved in a `.arena` folder in your home directory (one file per
  team). It proves you are that team: keep it private. If you lose it or want to
  play from another computer, ask the organiser for a new one (the old one then
  stops working).
* **Keep your key secret.** Anyone who has it can play as your team.
* **Use whatever you like.** The bot runs on your computer, so any library, any
  model, a GPU or an outside API is fine. Anything it costs is yours.
* **Connect before a round starts.** A match begins when both bots in the
  pairing are connected, and a team that is still missing after the grace
  period (the organiser tells you how long) forfeits the matches it has not
  played: its side folds every hand, which scores very badly.
* **One match at a time.** Your bot plays one match at a time and is told when a
  new one starts. If your bot has a method `on_match_start(self)`, it is called
  then: reset your notes about the opponent there.

If the arena refuses your connection, the message says why (a wrong join code,
a team name that is taken, registration closed, or an old client that needs
updating with `git pull`).

## The rules your bot must follow

| | |
|---|---|
| **Time** | 1 second hard limit per move, **including the network round trip** (the organiser may change this and will tell you). Load files and models when your bot starts, not in `act`. There is also a thinking-time budget of 3 seconds per hand on average over a match; going over it disables your bot for that match. |
| **Mistakes** | A crash, a timeout, an illegal move or a missing connection plays a safe default (check, otherwise fold) and counts as a fault. After 20 faults your bot is replaced by an always-fold stub for the rest of that match. |
| **If your connection drops** | The moves asked for while you are away are faults. Matches do not pause for you, so a stable connection matters. |
| **Memory between hands** | Your bot is one long-running program, so you may keep statistics about the current opponent. |
| **Fair play** | Each deal is played twice with the seats swapped. Your bot must not try to recognise a deal it has already seen and use the cards it remembers from the first half: that is cheating and gets a team disqualified. Do not attack the arena's server or other teams' connections either. |
| **Libraries** | Whatever you have installed on your own computer. |

Game format: heads-up (two players) no-limit Texas Hold'em, 100 big blinds,
blinds 10/20, stacks reset every hand.
