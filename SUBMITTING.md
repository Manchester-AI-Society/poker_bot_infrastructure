# How to submit your bot

For competitors. You keep your bot in **your own public GitHub repository**.
The organiser's computer pulls it automatically, checks it, and plays it. To
update your bot, push to your repository: nothing else to do.

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

## 2. Test it locally

```bash
python -m arena validate bots/myteam                    # does it load and play legally?
python -m arena match bots/myteam call --deals 200      # against a calling station
python -m arena match bots/myteam bots/equity_calc --deals 300
```

This is the same code and the same scoring the competition uses. If `validate`
says **OK**, your bot will be accepted. If a match shows `faults:` above zero,
read the log in `arena_logs/`.

## 3. Put it in your own repository

1. Create a **new public** repository on GitHub (private repositories cannot be
   pulled).
2. Put your `bot.py` at the **top level** of it, not in a folder. Any other files
   your bot needs (data files, helper modules) can sit next to it. Keep the
   whole repository under 25 MB.
3. Push it.

Your repository should look like this:

```
my-poker-bot/
  bot.py          <- required, at the top level
  strategy.py     <- optional extras
  data/           <- optional
```

## 4. Tell the organiser two things

* your **team name**: lowercase letters, digits, `-` and `_`, up to 32
  characters (for example `team-fox`);
* the **address of your repository**, for example
  `https://github.com/team-fox/poker-bot`. It must start with `https://`, and
  must not contain a password or token. If you want a branch other than the
  default one, say which.

The organiser adds you to the teams list. A minute or so later your bot is
fetched, checked, and playing.

## 5. Update your bot as often as you like

Push to your repository. About a minute later the organiser's computer fetches
the new version and checks it:

* **It loads and plays legally:** it replaces your old bot and plays against
  everyone again.
* **It fails the check:** your **previous version keeps playing**, so a mistake
  never takes you out of the competition. The reason is shown against your team
  on the website's **Submissions** page, and you can reproduce it locally with
  `python -m arena validate`.
* **Nothing changed:** nothing happens.

The website is updated every few minutes, so allow a little time before a result
or a message appears.

Only the **final** decides the winner. Near the end the organiser takes a
snapshot of every team's latest working bot and plays a larger round robin on
those exact versions. Anything you push after the snapshot is ignored, so push
your best bot **before the deadline**.

## If something goes wrong

The **Submissions** page of the results website tells you what happened to your
last fetch:

| You see | What it means | What to do |
|---|---|---|
| Could not fetch the repository | The address is wrong, or the repository is private | Check the address; make the repository public |
| Fetched but cannot be used: the bot directory must contain bot.py | `bot.py` is missing from the top level | Move it to the top level and push |
| Fetched but cannot be used: identical code was already submitted by ... | Your code is byte-for-byte the same as another team's | Submit your own bot |
| Latest push failed: (an error) | Your bot loaded but crashed or played an illegal move | Run `python -m arena validate` and read `arena_logs/` |

## The rules your bot must follow

| | |
|---|---|
| **Time** | 1 second hard limit per move. Do slow set-up (loading files) when your bot starts, not in `act`. There is also a small thinking-time budget over a match; going over it disables your bot for that match. |
| **Mistakes** | A crash, a timeout or an illegal move plays a safe default (check, otherwise fold) and counts as a fault. After 20 faults your bot is replaced by an always-fold stub for that match. |
| **Memory between hands** | Your bot keeps running across many hands, so you may keep opponent statistics. It restarts for the second half of a match, so do not rely on memory beyond that. |
| **Libraries** | Python's standard library, and what `requirements.txt` installs. Ask the organiser before relying on anything else. |
| **Not allowed** | Reading other teams' code or files, using the network, or reading anything outside your own repository. Your code runs on the organiser's computer without a sandbox, so this is a rule of trust: breaking it gets a team disqualified. |

Game format: heads-up (two players) no-limit Texas Hold'em, 100 big blinds,
blinds 10/20, stacks reset every hand. Each deal is played twice with the seats
swapped to remove card luck, and scores are shown in big blinds per hand with a
95% confidence interval.
