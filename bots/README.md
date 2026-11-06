# Example bots

Seven working bots to learn from, test against, and beat. Each is one
self-contained `bot.py` (a team's folder is all that gets packed, so a bot
cannot import another bot). Read the docstring at the top of each file: it says
what the bot does and how to try it.

Every bot's `act(game_state)` returns a `Response`: `Response.fold()`,
`Response.call()` (checks when nothing is owed), `Response.raise_to(total)` or
`Response.all_in()`. Anything else, or an amount outside
`game_state.min_raise_to` to `game_state.max_raise_to`, counts as a fault. The
older name `Action` still works for `Response`.

| Folder | Style | Strong against | Weak against |
|---|---|---|---|
| `starter/` | Tight and honest: raises strong hands, calls at the right price. The one to copy when you begin. | calling stations, random play | anything that bluffs well |
| `tight_aggressive/` | Few hands, played hard; value bets, sometimes a continuation bet, position-aware. | passive players | players who raise it off hands |
| `loose_aggressive/` | Plays most hands, raises and re-raises, keeps betting. | players who fold too much | players who call down |
| `the_rock/` | Only premium hands, never bluffs. | being bluffed into mistakes (it can't be) | aggressive players; the blinds eat it |
| `equity_calc/` | Simulates the hand on every decision and bets when it is ahead. Has its own hand evaluator. | most simple styles (it ranked first in a 150-deal sample ladder, though within the margin of error) | players who only bet strong hands |
| `adaptive/` | Learns how often the opponent folds and how aggressive they are, then exploits it. | folders and maniacs, once it has seen ~12 spots | opponents who change style |
| `push_fold/` | Shoves its best hands, folds the rest. | opponents who fold to pressure | anyone who calls with a better hand |

"Strong against" and "weak against" are what each style is built to do; they
are not guarantees. Results move with luck, which is why the arena plays every
deal twice and shows a confidence interval.

## Try one

```bash
python -m arena match bots/equity_calc call --deals 200
python -m arena match bots/tight_aggressive bots/loose_aggressive --deals 300
```

(`call`, `fold`, `random` and `shove` are built-in opponents.)

## Make your own

```bash
cp -r bots/starter bots/myteam      # PowerShell: Copy-Item -Recurse bots\starter bots\myteam
python -m arena validate bots/myteam
python -m arena match bots/myteam bots/equity_calc --deals 300
```

## Pack one to submit

When your bot is ready, pack it into one zip and upload that zip in the
submission form (see [SUBMITTING.md](../SUBMITTING.md)):

```bash
python -m arena pack bots/myteam --team myteam
```

This checks the bot again and writes `myteam.zip` in the current folder.

## Run them as a small competition

This rehearses the whole event with the example bots, the way the organiser
runs it (see [ORGANISER.md](../ORGANISER.md)). Everything goes into folders that
git ignores.

```bash
for b in tight_aggressive loose_aggressive the_rock equity_calc adaptive push_fold; do
  python -m arena pack bots/$b --team ${b//_/-} --out downloads/demo
done
```

```powershell
foreach ($b in "tight_aggressive","loose_aggressive","the_rock","equity_calc","adaptive","push_fold") {
  python -m arena pack bots/$b --team $b.Replace("_","-") --out downloads/demo
}
```

Then import the zips, draw the groups, and play (the second command prints the
groups; leave `run` going and start the next steps in another window):

```bash
python -m arena import downloads/demo --root arena_data/demo
python -m arena tournament draw --group-size 4 --advance 2 --root arena_data/demo
python -m arena tournament start-groups --deals 50 --root arena_data/demo
python -m arena tournament run --root arena_data/demo
```

When `python -m arena tournament status --root arena_data/demo` says
`phase: between`, run `python -m arena tournament start-finals --deals 100
--root arena_data/demo`. Press Ctrl+C in the `run` window when the status says
`phase: done`; it prints the champion.

Two teams cannot submit byte-identical code (the second is rejected as copied),
so change something in a copy if you want two of the same bot.
