# Poker bot competition

A heads-up no-limit Texas Hold'em competition for Python bots. You write a bot,
test it on your own computer, pack it into one zip file and upload it through a
form. The organiser plays everyone's bot on one machine.

* **Round 1, groups.** Teams are drawn at random into groups of at most 8. Each
  group plays a round robin.
* **Round 2, finals.** The best 2 bots of each group play a round robin. The
  final table decides the winner.
* **No live standings.** Nothing about results is published until a round is
  finished. The group tables appear when Round 1 ends, the final table when
  Round 2 ends.

Each deal is played twice with the two bots swapping seats, so card luck mostly
cancels. A score is the average number of big blinds won per hand, with a 95%
confidence interval. Blinds are 10/20 and stacks are 2000 chips, reset every
hand.

## What you need

* Python 3.11 or newer.
* Git.
* This repository. Nothing else: your bot runs on the organiser's machine, not
  on yours.

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
wrong. Seven working example bots are described in [bots/README.md](bots/README.md).

## Test it locally

```bash
python -m arena validate bots/myteam
python -m arena match bots/myteam call --deals 200
python -m arena match bots/myteam bots/equity_calc --deals 300
```

`validate` checks that your bot loads and plays legally. `match` plays your bot
against a built-in opponent (`call`, `fold`, `random`, `shove`) or against
another bot folder, with the same engine and scoring as the competition. If a
match shows `faults:` above zero, the first fault is printed with its reason (for
example `raise_to(1) is outside the allowed range: the total must be between 40
and 2000 chips`). `validate` prints it too. The folder `arena_logs/` holds what
your bot printed, any crash output, and a line for each illegal response.

## Pack and submit

Pack your bot into one zip. This checks it again and writes `myteam.zip` in the
current folder:

```bash
python -m arena pack bots/myteam --team myteam
```

Choose your team name once: lowercase letters, digits, `-` and `_`, up to 32
characters. Then upload `myteam.zip` in the submission form. The organiser will
share the form link.

You can submit again until the deadline. Pack again and upload the new zip: the
newest zip that works is the one that plays. A newer zip that is broken never
replaces a working one.

## The rules

| | |
|---|---|
| **Time** | 1 second per move. Your average thinking time is also limited to 0.2 seconds per deal per half; going over disables your bot for that match. Load files at start-up, not inside `act`. |
| **Mistakes** | An exception, a timeout, an illegal move, or a return value that is not a `Response` is a fault. A safe default is played (check, otherwise fold) and the reason is reported (`validate` and `pack` print it). After 20 faults your bot is replaced by an always-fold stub for that match. |
| **Memory** | The arena does not limit it, but several matches run at once on one machine. Keep your bot small and do not hold on to large data. Your bot is restarted for each half of a match, so it starts each half fresh. |
| **Size** | The bot folder, all files unzipped, must be at most 25 MB. |
| **Libraries** | The Python standard library and what `requirements.txt` installs. The organiser will say if anything else is installed. CPU only. |
| **Fair play** | No network use. Do not read files outside your own bot folder. Do not attack the arena or other teams' bots. Breaking these rules gets a team disqualified. |

## More

* [SUBMITTING.md](SUBMITTING.md): the full competitor guide.
* [bots/README.md](bots/README.md): the example bots and how to use them.
* [ORGANISER.md](ORGANISER.md): how the event is run (for the organiser).
* [ARCHITECTURE.md](ARCHITECTURE.md): how the arena works inside.
* [docs/legacy-server.md](docs/legacy-server.md): the older network match
  server and SDK, which the competition does not use.

This project is licensed under the [MIT License](LICENSE).
