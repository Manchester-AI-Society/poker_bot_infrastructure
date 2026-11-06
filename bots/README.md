# Your bot

`starter/` is the template. Copy it, rename the copy, and write your bot in it.
A bot is one `bot.py` with exactly one class that extends `PokerBot`; its
`act(game_state)` method returns a `Response` each time it is your turn:

* `Response.fold()`
* `Response.call()` (checks when nothing is owed)
* `Response.raise_to(total)` (between `game_state.min_raise_to` and `game_state.max_raise_to`)
* `Response.all_in()`

Anything else, or an amount outside that range, costs you the turn (a safe move
is played instead). The docstring at the top of `starter/bot.py` explains what
`game_state` holds.

```bash
cp -r bots/starter bots/myteam      # PowerShell: Copy-Item -Recurse bots\starter bots\myteam
python -m arena validate bots/myteam
python -m arena match bots/myteam call --deals 200
```

`call`, `fold`, `random` and `shove` are built-in opponents; you can also play
your bot against another bot folder. [SUBMITTING.md](../SUBMITTING.md) has the
full guide, from setting up to joining the event.
