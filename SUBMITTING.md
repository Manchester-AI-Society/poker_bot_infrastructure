# How to enter your bot

For competitors. You write a Python bot, test it on your own computer, pack it
into one zip file and upload that zip through the organiser's submission form.
The organiser runs every bot on one machine. Your bot never connects to
anything, and you do not need to leave anything running.

## How the competition works

There are **two rounds** and no live leaderboard.

* **Round 1, groups.** Every team is drawn at random into a group of at most 8.
  Each group plays a round robin: everyone plays everyone else in the group.
* **Round 2, finals.** The best 2 bots of each group play a round robin among
  themselves. The best finals score wins.

Nothing about how anyone is doing is published while a round is being played.
The group tables appear when Round 1 is complete, and the final table when
Round 2 is.

Every match is a number of **deals** (the organiser decides how many). Each deal
is played twice with the two bots swapping seats, so card luck mostly cancels.
The score is in big blinds per hand with a 95% confidence interval. Blinds are
10/20 and stacks are 2000 chips, reset every hand.

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

Your bot is a folder with a `bot.py` and exactly one `PokerBot` class that has
a constructor taking no arguments. Other files in the folder (data, helper
modules) are fine; they travel in the zip.

`act(game_state)` is called each time it is your turn and must return a
`Response`:

* `Response.fold()` gives up the hand.
* `Response.call()` calls, or checks when nothing is owed.
* `Response.raise_to(total)` bets or raises. `total` is the total number of
  chips you want in the pot this betting round, between `game_state.min_raise_to`
  and `game_state.max_raise_to`.
* `Response.all_in()` puts in everything you have left.

Anything else (a string such as `"call"`, `None`, an amount outside the range, a
raise when raising is not allowed) is a fault: see the rules below. `Action` is
an older name for `Response` and still works.

### What your bot is given

`act(game_state)` receives a `GameState`. These are the details that are easy
to guess wrong:

| | |
|---|---|
| **Cards** | Two-character strings: rank then suit, both upper case, with `T` for ten: `AS`, `TD`, `7H`, `2C`. The suits are `S`, `H`, `D`, `C`. |
| **pot_size** | The chips in the middle right now, including bets already made this round. At the start of a hand it is 30 (the two blinds). |
| **call_amount** | The chips you must add to stay in. Zero means you can check. |
| **min_raise_to, max_raise_to** | The smallest and largest total you may give to `Response.raise_to`. Only meaningful when you can bet or raise (`can_bet`, `can_raise`). |
| **legal_actions** | Only the moves you may make, from `fold`, `check`, `call`, `bet`, `raise_to`. `bet` appears only when nobody has bet this round. `Response.call()` covers both `call` and `check`. |
| **action_history** | This hand so far. Each record has `player_id`, `action`, `amount` and `street`. Actions are `post_small_blind`, `post_big_blind`, `fold`, `check`, `call`, `bet` and `raise_to`. For `call` and `bet` the amount is the chips added; for `raise_to` it is the total you have in this round. |
| **Your class** | Exactly one `PokerBot` subclass, with a constructor that takes no arguments. |

## 2. Test it locally

```bash
python -m arena validate bots/myteam                    # does it load and play legally?
python -m arena match bots/myteam call --deals 200      # against a calling station
python -m arena match bots/myteam bots/equity_calc --deals 300
```

This is the same engine and the same scoring the competition uses. If `validate`
says **OK**, your bot plays legally. If a match shows `faults:` above zero, run
`python -m arena validate bots/myteam`. A mistake in your response is reported
as one sentence, for example that a raise was outside the allowed range. A crash
shows the end of the traceback. The folder `arena_logs/` (or the folder you give
with `--log-dir`) holds what your bot printed, any crash output, and a line for
each illegal response.

## 3. Pack it

```bash
python -m arena pack bots/myteam --team myteam
```

`pack` checks your bot again, then writes `myteam.zip` (with a small manifest
and a checksum) into the current folder. Use `--out FOLDER` to put it somewhere
else. Pick your team name once and keep using it: lowercase letters, digits, `-`
and `_`, up to 32 characters.

If `pack` says your bot fails its check, fix that first: `validate` shows the
same check.

## 4. Upload it

Open the submission form (the organiser shares the link), enter the same team
name you gave to `pack`, and upload the zip. The form has no way to check the
file, which is why `pack` does it for you.

You can submit again until the deadline: pack again and upload the new zip. The
newest zip that works is the one that plays. A newer zip that turns out to be
broken never replaces a working one, and a team name is not reserved, so use a
name that is clearly yours.

## The rules your bot must follow

| | |
|---|---|
| **Time** | 1 second hard limit per move (the organiser may change this and will tell you). Load files and models when your bot starts, not in `act`. There is also a thinking-time budget of 0.2 seconds per deal per half on average; going over it disables your bot for that match. |
| **Mistakes** | A crash, a timeout, an illegal move or a return value that is not a `Response` plays a safe default (check, otherwise fold), and counts as a fault; `validate` and `pack` show you the reason. After 20 faults your bot is replaced by an always-fold stub for the rest of that match. |
| **Memory between hands** | Your bot is one long-running program for each half of a match, so you may keep statistics about the current opponent. It is started fresh for each half. |
| **Size** | All files in your bot folder, unzipped, must total at most 25 MB. |
| **Libraries** | The Python standard library and whatever `requirements.txt` installs. The organiser will tell you if anything else is installed. CPU only. |
| **Fair play** | No network use. Do not read files outside your own bot folder. Do not attack the arena or other teams' bots. Breaking these rules gets a team disqualified. |

Your bot runs on the organiser's computer, so everything it needs must be in
the zip. Game format: heads-up (two players) no-limit Texas Hold'em, 100 big
blinds, blinds 10/20, stacks reset every hand.

## What happens next

After the deadline the organiser downloads every uploaded zip and imports them.
Each zip is treated as untrusted and checked again; a file that cannot be read
is refused, and a bot that fails its check is not played. Identical code from
two teams is rejected as copied, so do not submit someone else's bot. Then the
groups are drawn, Round 1 is played, and Round 2 follows. Results are shown on
the results website when each round is complete.
