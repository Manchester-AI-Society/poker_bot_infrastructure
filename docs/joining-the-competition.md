# Joining the competition

You write a Python poker bot. On the day, it connects to our server and plays a no-limit Texas Hold'em knockout tournament against everyone else's bots. The server deals the cards and enforces the rules. Your bot only decides **fold, call or raise** each turn.

**You'll need:** Python 3.11+, a laptop, and any Wi-Fi (eduroam is fine).

## 1. Set up (before the event)

```bash
git clone https://github.com/Manchester-AI-Society/poker_bot_infrastructure.git
cd poker_bot_infrastructure
python3 -m venv venv && source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt && pip install -e .
```

This gives you the bot SDK, the `poker-bot` command, and a local server for testing.

## 2. Write your bot

Make a file, e.g. `my_bot.py`, with **one** class that subclasses `PokerBot` and implements `act`:

```python
from player_sdk.bot_interface import PokerBot
from player_sdk.models import Action, GameState


class MyBot(PokerBot):
    def act(self, state: GameState) -> Action:
        try:
            if state.call_amount == 0:
                return Action.call()                  # free to continue → check
            if state.call_amount <= state.my_stack // 10:
                return Action.call()
            return Action.fold()
        except Exception:
            return Action.fold()                      # never let your bot crash
```

### The three actions

| Return | Meaning |
|---|---|
| `Action.fold()` | Give up the hand |
| `Action.call()` | Match the current bet. If there's nothing to call, this **checks**. |
| `Action.raise_to(amount)` | Bet or raise so your total bet this round is `amount`. Must be between `state.min_raise_to` and `state.max_raise_to`; `max_raise_to` is all-in. |

### What your bot can see (`state.…`)

| Field | Meaning |
|---|---|
| `hole_cards` | Your two cards, e.g. `("AH", "3H")`: rank `2–9 T J Q K A`, suit `C D H S` |
| `community_cards` | The board (0, 3, 4 or 5 cards) |
| `street` / `is_preflop` … `is_river` | Which betting round it is |
| `call_amount` | Chips you need to put in to call (`0` means you can check) |
| `my_stack`, `my_bet` | Your chips left, and what you've put in this round |
| `min_raise_to`, `max_raise_to` | Legal range for `Action.raise_to(...)` |
| `pot_size` | Chips in the middle |
| `stack_sizes`, `current_bets`, `folded`, `all_in`, `player_ids` | Everyone at the table, by seat (`my_index` is you) |
| `action_history` | What's happened so far: `player_id`, `action`, `amount`, `street` |

`examples/bots/conservative_bot.py` is a complete working example.

### Rules your bot lives by

- **Answer fast.** Every turn has a time limit (about 15s, set by the organisers). If time runs out, the server checks for you, or folds if checking isn't allowed.
- **Invalid moves are rejected.** If you raise outside `min_raise_to`–`max_raise_to`, the server rejects it (you'll see `server: …` in your terminal) and your turn can time out. Clamp your amount: `max(state.min_raise_to, min(amount, state.max_raise_to))`.
- **If `act` throws, your bot process dies** and every remaining turn times out. Keep the `try/except` above.
- **Blinds double regularly**, so waiting for perfect cards forever loses.

## 3. Test it locally

```python
# test_my_bot.py
from my_bot import MyBot
from examples.bots.conservative_bot import ExampleConservativeBot
from player_sdk.testing import play_local_match

result = play_local_match([MyBot(), ExampleConservativeBot()], max_hands=50)
print(result.winner_id, result.final_stacks)
```

```bash
python test_my_bot.py
```

This starts a local server for you and plays up to 50 hands (the chip leader wins if nobody's busted by then). Run it until your bot doesn't crash and wins sometimes.

## 4. On the day: get your key

The organisers will show a **server URL** and a **join code** on screen. Pick a team name (letters, digits, `-` and `_` only) and run:

```bash
curl -X POST https://<server-url>/v1/register -H 'Content-Type: application/json' \
  -d '{"player_id": "YOUR-TEAM-NAME", "code": "<join-code>"}'
```

You'll get back:

```json
{"player_id": "YOUR-TEAM-NAME", "api_key": "3f9c…"}
```

**Save that `api_key`.** It's yours and can't be looked up again.

- `409` means the name is taken; pick another.
- `403` means the join code is wrong.
- No `curl`? Ask an organiser and they'll give you a key directly.

To check your key works:

```bash
curl https://<server-url>/v1/me -H "Authorization: Bearer <your-key>"   # → {"player_id": "YOUR-TEAM-NAME"}
```

## 5. Join the tournament

```bash
poker-bot my_bot.py --tournament --server-url https://<server-url> --api-key <your-key>
```

You'll see:

```
[player_sdk] Playing as YOUR-TEAM-NAME (websocket)
[player_sdk] Waiting in the tournament lobby
```

**Leave it running.** When the organisers start the tournament:

1. **Round 1:** everyone is shuffled onto tables that play until one bot has all the chips.
2. **Final:** each table winner moves to the final table. The winner of that is champion.

Your terminal shows each hand and ends with either `Eliminated in round N` or `Tournament over; champion: …`.

**Join before the start.** Only bots in the lobby when the tournament starts get a seat.

Prefer Python over the CLI?

```python
from player_sdk import play_tournament
from my_bot import MyBot

print(play_tournament(MyBot(), api_key="<your-key>", server_url="https://<server-url>"))
```

## Troubleshooting

| Problem | Fix |
|---|---|
| `Invalid API key` / `401` | Typo in the key, or the server was restarted. Register again (same name is fine after a restart). |
| `Could not reach server` | Check the URL (it must start with `https://`, with no `:8000`). Open `https://<server-url>/health` in a browser. If it shows `{"ok":true}`, the server is up. |
| Bot exits with a Python error | Bug in your `act`. Fix it, then rerun the same `poker-bot` command. Rejoin before the tournament starts if you can. |
| Bot keeps folding without your code running | Your `act` is too slow; the turn timer acted for you. |
| `Expected exactly one PokerBot subclass in my_bot.py` | Keep only one `PokerBot` class in `my_bot.py`, with no constructor arguments. |

Everything else, including the HTTP/websocket API and running your own server, is in the main [README](../README.md).
