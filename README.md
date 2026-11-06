# Poker bot competition

Write a Python poker bot, test it on your own computer, pack it into one
`.pkl` file and upload it through the submission form. The organiser plays
everyone's bot on one machine. **The prize pot is £300.**

## The event

| Time | What happens |
|---|---|
| **12:00** | Hacking starts. Set up, write your bot, test it. |
| **18:00** | Submission deadline. Upload your `.pkl` in the form; the last working one you upload is the one that plays. |
| **After 18:00** | The round: every bot plays every other bot. |

* **One round.** Every submitted bot plays every other bot (a round robin of
  heads-up matches). The bot with the best score is the champion.
* **No live standings.** Nothing about results is published until the round is
  finished. Then the table and the champion appear on the event website.

Each deal is played twice with the two bots swapping seats, so card luck mostly
cancels. A score is the average number of big blinds won per hand, with a 95%
confidence interval. Blinds are 10/20 and stacks are 2000 chips, reset every
hand.

## 1. Set up

You need **Python 3.14** and git. A pickle holds Python bytecode, so you must
pack with the same Python version the organiser plays with, and `arena pack`
refuses any other.

```bash
git clone https://github.com/Manchester-AI-Society/poker_bot_infrastructure.git
cd poker_bot_infrastructure
python -m venv venv
venv\Scripts\activate          # macOS and Linux: source venv/bin/activate
python -m pip install -r requirements.txt
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

Anything else, or an illegal amount, is a mistake (see the rules below).

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

**Your bot travels as a pickle.** `arena pack` saves the *object* your class
makes (everything in `bot.py` and any helper `.py` files next to it are stored
inside the file). So:

* Load models and data in `__init__` and keep them in plain attributes. Files on
  disk are **not** available when the organiser plays your bot, and open files,
  sockets and locks cannot be pickled.
* Libraries stay installed on the organiser's machine, not in your file: use the
  Python standard library and what `requirements.txt` installs, CPU only.

## 3. Test it on your computer

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
and 2000 chips`). The folder `arena_logs/` holds what your bot printed and any
crash output.

## 4. Pack and submit

Pack your bot into one `.pkl` file. This checks it again, the way the organiser
will run it (loaded from the pickle alone, in a fresh process), and writes
`myteam.pkl` in the current folder:

```bash
python -m arena pack bots/myteam --team myteam
```

Choose your team name once: lowercase letters, digits, `-` and `_`, up to 32
characters. Then upload `myteam.pkl` in the submission form (the link is on the
event website). You can submit again until 18:00: pack again and upload the new
file. The newest file that works is the one that plays, and a newer file that is
broken never replaces a working one.

## The rules

| | |
|---|---|
| **Time** | 1 second per move. Your average thinking time is also limited to 0.2 seconds per deal per half; going over disables your bot for that match. Load files at start-up (in `__init__`), not inside `act`. |
| **Mistakes** | An exception, a timeout, an illegal move, or a return value that is not a `Response` is a fault. A safe default is played (check, otherwise fold) and the reason is reported (`validate` and `pack` print it). After 20 faults your bot is replaced by an always-fold stub for that match. |
| **Memory** | The arena does not limit it, but several matches run at once on one machine. Keep your bot small. Your bot is restarted for each half of a match, so it starts each half fresh. |
| **Size** | The `.pkl` file must be at most 25 MB. |
| **Fair play** | No network use. Do not read files outside your own bot. Do not attack the arena or other teams' bots. Breaking these rules gets a team disqualified. |

## If something goes wrong

| What you see | What to do |
|---|---|
| `pack with Python 3.14` | You are on another Python version. Install 3.14 and make a new venv with it. |
| `your bot does not load` | `bot.py` raised an error on import; the message says where. |
| `cannot be pickled` | Your bot holds an open socket or lock. Create it only inside `act`, or drop it, and keep plain data in `__init__`. |
| `Expected exactly one PokerBot subclass` | Keep only one `PokerBot` class in `bot.py`, with no constructor arguments. |
| `your bot fails its check` | The message gives the first fault (a crash, an illegal raise, or a slow move). `python -m arena validate bots/myteam` shows the same check. |
| The organiser says your file was rejected | It was not made by `arena pack`, was damaged or edited, or was packed with another Python version. Pack it again and upload it again. |

## For the organiser

State lives under `arena_data/` (the downloaded form uploads go in any folder).

```bash
python -m arena import downloads                       # read every .pkl, check each bot
python -m arena tournament draw --single-round         # everyone in one group
python -m arena tournament start-groups --deals 100
python -m arena tournament run                         # leave running until status says done
python -m arena tournament status
python -m arena export --out arena_site --git-push     # publish the site (Home text: event.json)
```

For two rounds (groups, then finals) draw with `--group-size 8 --advance 2`
instead and run `start-finals` when status says `between`.

Unpickling runs the team's code, so bots are not sandboxed: run the event on a
machine you can spare. A file's label is read without running anything, and the
bot inside is only ever unpickled in the child process that plays it. The
earlier docs (organiser runbook, architecture notes) and the websocket
version are on the `try/ammar-websockets` branch.

This project is licensed under the [MIT License](LICENSE).
