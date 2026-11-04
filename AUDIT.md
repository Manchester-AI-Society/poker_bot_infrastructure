# Audit — poker bot infrastructure (Phase 1)

Scope: whole repo at `c89c7b2` (`game/`, `server/`, `player_sdk/`,
`admin_sdk/`, tests, CI, Docker). **No engine/server code was changed.**
Added only: this file and `tests/test_audit_regressions.py`.

How findings were checked: full read of `game/`, `server/`, `player_sdk/`;
existing suite run (97 unit tests pass); every Critical/High item below has a
reproduction in `tests/test_audit_regressions.py` (12 tests, `xfail(strict=True)`
— CI stays green now, and each fix *must* remove its marker or the run fails).
Throughput numbers were measured on this machine (Windows, Python 3.14).

Severity: **critical** = wrong results or cheating possible / match can
deadlock; **high** = wrong behaviour that will hit a real tournament;
**medium** = real but contained; **low** = polish.

## 0. How the system actually works (matters for everything below)

* One FastAPI process holds every match in memory (`GameService`,
  `game/game_service_core.py`). There is no database; a restart loses all
  matches.
* **The server never runs bot code.** Bots are *remote clients*: each
  participant runs `player_sdk` on their own machine and talks to the server
  over WebSocket (`/v1/ws`) or HTTP polling. Auth is one API key per bot.
* Matches are N-player (≥2) freeze-outs: play hands until one player holds
  every chip or `max_hands` is hit (default: unlimited). Constant blinds.
* README itself says "side-pot-free settlement" — that was a known
  simplification, but it is incorrect as soon as stacks differ, and stacks
  differ after the first hand (see C1).

**Consequence for your brief:** several things the brief assumes — uploaded
bots, a submission/validation pipeline, bot logs visible to a team, sandboxing —
do not exist, because today participants *self-host* their bots. That is the
central Phase 2 decision (see "Open questions").

---

## 1. Bugs

### C1 — No side pots; uncalled chips are never returned — **critical**
`game/showdown_resolver.py:38-63`, `game/action_engine.py:150-177`.
`settle_showdown` gives the *entire* pot to the best hand among non-folded
players. Nothing tracks per-player contribution, and `raise_to` is limited only
by the raiser's own stack, not by what anyone can call.
* Heads-up, stacks 1000 vs 200: p0 raises to 600, p1 calls all-in for 200,
  p1 has the nuts. p1 should win 400 (final stacks 800/400); engine pays p1 the
  whole 800 pot (400/800). Every uneven-stack all-in is mis-settled, and stacks
  are uneven after hand 1.
* 3-way, short stack all-in with best hand wins the *whole* pot, including the
  side pot it has no claim on (repro: 700 instead of 300).
* Fold path (`settle_fold_win`) is fine for fold-wins, but an uncalled bet that
  is folded to is returned only because it lands in the winner's pot.

Tests: `test_c1_heads_up_uncalled_excess_is_returned`,
`test_c1_three_way_short_stack_wins_main_pot_only`.
Fix: track `total_committed` per player per hand; at showdown build pots from
the distinct contribution levels, return the uncalled top slice to its owner,
award each pot only among eligible (non-folded) contributors, split ties inside
each pot. ~80 lines + tests; the single biggest correctness fix.

### C2 — An all-in raise ends the betting round; opponent is never asked to respond — **critical**
`game/poker_game.py:139-148` (`round_has_pending_actions`),
`game/runtime_flow.py:70-103`.
`round_has_pending_actions` returns `False` whenever ≤1 player can still act.
When a raise makes the raiser all-in and exactly one other player is active,
the street advances immediately: `_reset_street_data` zeroes `call_amount` and
all street bets, so the facing player's decision (call/fold) is silently erased
and they see the rest of the board for free. Net effect: **shoving heads-up is
auto-"called" with fold equity removed** — any bot that shoves is exploitable,
and results are wrong. Also affects multiway when all other players but one are
all-in.
Test: `test_c2_opponent_must_answer_a_heads_up_shove`.
Fix: with one active player left, a round is pending iff that player's
`curr_bet_amount < call_amount`; the ≤1 shortcut is only valid when nobody owes
a response. (Same function also fixes H1.)

### C3 — Any client can read any player's hole cards — **critical**
`server/api/routers/match_management_routes.py:111-131`.
`GET /v1/matches/{id}?viewer_id=<anyone>` is unauthenticated and trusts the
query param. `curl …?viewer_id=victim` returns the victim's `hole_cards`
(mid-hand, live). The SDK itself uses this endpoint (`client.py:172,190`), so it
is the *designed* path, not an oversight. `/v1/matches` and `/v1/bots` are also
unauthenticated (low).
Test: `test_c3_state_endpoint_does_not_leak_other_players_hole_cards`.
Fix: require the bot key; derive viewer from the key, ignore `viewer_id`;
unauthenticated/spectator view never includes live hole cards (completed hands
only, for the replayer). Update SDK + `play_local_match` accordingly.

### C4 — One illegal action permanently stalls the match — **critical**
`game/game_service_core.py:329-337`.
`submit_action` cancels the turn timer *before* `apply_action` validates. If the
action is illegal the exception propagates, the timer is gone and nothing
re-arms it. The WS runner just logs the server `error` and waits for a
`your_turn` that never comes (it recovers only via a 5 s idle HTTP re-act that
resubmits the same deterministic illegal move, forever). One buggy bot (very
common: raise below min, bet when must raise) freezes its match with no
recovery except an admin `end`.
Test: `test_c4_turn_timer_survives_an_illegal_action`.
Fix: validate first, cancel the timer only on success (or re-arm in `except`).
Policy choice for Phase 2: illegal action → error + keep clock running, or
auto-clamp/fold after N strikes.

### H1 — Lone active player is asked to act against an all-in opponent — **high**
`game/runtime_flow.py:95-103`: after advancing a street the loop `break`s unless
*all* remaining players are all-in. If one player is all-in and the other has
chips left (and has matched), the covering player is prompted on flop, turn and
river (can even `bet` into dead money, and waits a timeout per street).
Test: `test_h1_hand_runs_out_when_only_one_player_can_act`.
Fix: with ≤1 player able to act and nothing owed, run out the board. Same patch
as C2.

### H2 — Short stack cannot shove if stack < min-raise — **high**
`game/action_engine.py:160-165`: `raise_to` rejects `amount < min_raise_to` even
when `amount == max_raise_to` (all-in). Bot at 30 chips facing a 20 BB option
has `min_raise_to=40 > max_raise_to=30`: `legal_actions` offers `raise_to`, but
no amount is valid. Push/fold bots (very likely at 50 BB stacks) cannot jam
short. Test: `test_h2_short_stack_can_shove_below_min_raise`.
Fix: accept `amount == max_raise_to` always; treat it as a non-reopening
("incomplete") raise when `< min_raise_to`; report `min(min_raise_to,
max_raise_to)` to bots. Note `reset_acted_flags_after_aggression` currently
reopens action on *every* raise — needs the incomplete-raise rule too.

### H3 — Big-blind option: engine advertises `bet`; SDK sends `bet` for a raise — **high**
`game/action_engine.py:15-18`, `player_sdk/client.py:41-43`.
With everyone limped, `to_call == 0` but `call_amount == BB`, so `legal_actions`
lists `bet` (which the handler then refuses: "Use raise_to when a bet already
exists"), and `translate_action` turns `Action.raise_to()` into `bet` because
the SDK's `call_amount` is *to-call* (0). **SDK bots can never raise from the BB
option**, and combined with C4 this stalls the match.
Test: `test_h3_sdk_raise_from_big_blind_option_is_accepted`.
Fix: list `bet` only when `engine.call_amount == 0`; SDK should choose
`bet`/`raise_to` from `legal_actions`, not from `call_amount`.

### H4 — Malformed `amount` over WebSocket crashes the handler / corrupts chips — **high**
`server/api/routers/realtime_websocket_gateway.py:76-95`,
`game/action_engine.py:159-175`. The HTTP route validates with pydantic; the
WS path passes `payload.get("amount")` straight through.
* `"amount": "lots"` → `TypeError` (not in the `except` tuple) → handler dies,
  connection entry is not cleaned, and with C4 the timer is already cancelled.
* `"amount": 45.5` is *accepted*: balances/pot become floats (fractional chips).
  `true` (bool) is an int in Python and would be accepted as 1.
Tests: `test_h4_non_numeric_amount_is_an_invalid_action_not_a_crash`,
`test_h4_fractional_amount_is_rejected`.
Fix: validate `isinstance(amount, int) and not bool` in the service (single
choke point), wrap the WS loop body in a catch-all that replies `error`, and
tolerate non-dict / invalid JSON frames.

### H5 — `.env` is read too late; insecure public default keys incl. admin — **high**
`server/run_poker_server.py:3-5`, `server/api/shared_runtime_dependencies.py:54-55`,
`server/server_settings.py:37-71`.
`run_poker_server` imports the app (which executes `load_api_keys()` at import)
*then* calls `load_dotenv()`. So `.env` values never reach the server when
started with the documented `uvicorn server.run_poker_server:app`; it silently
falls back to `dev-key-1…3` and **`admin-dev-key`** (publicly documented). A
server started "with keys configured" is in fact fully open to anyone who read
the README. Docker only works because compose injects real env vars.
Test: `test_h5_dotenv_keys_are_used_by_the_server`.
Fix: load dotenv before importing the app; remove default keys unless
`POKER_DEV=1`, otherwise refuse to start; compare keys with
`secrets.compare_digest`.

### H6 — A crashed/disconnected bot costs a full turn timeout every turn — **high**
`game/turn_timeout_manager.py:53-82`, `game/runtime_flow.py`. A dead bot is
auto-checked/folded only after `turn_timeout_seconds` (default 15 s) on *every*
decision; there is no forfeit and no use of `connected_check` to skip the wait.
A freeze-out against a dead bot is ~tens of hands × 15 s ≈ 10–20 min of pure
waiting per match. In a round robin that dominates wall-clock. (No repro test:
needs a policy decision.)
Fix: if the player has no live socket, act immediately; after K consecutive
timeouts mark `forfeit`, fold instantly thereafter / end match with
`end_reason=forfeit`, and surface it in results.

### H7 — Deck RNG is unseeded global `random`; not reproducible — **high** (fairness)
`game/poker_deck.py:23`. See §3. Also what blocks duplicate poker.

### H8 — Hand history is bounded and incomplete: replays/disputes impossible — **high**
`game/match_runtime.py:43` (`deque(maxlen=event_log_limit)`, default 2000),
`game/game_service_core.py:569-582`.
~15 events/hand ⇒ oldest hands are dropped after ~130 hands. The log also never
records hole cards, the full board, per-hand starting stacks, or the deck, and
showdown only records hand *names*. So neither the hand replayer (Phase 3) nor
"why did I lose?" disputes can be served. Fix: append-only per-hand record
(JSONL or SQLite) written at hand end with seed, stacks, seats/button, every
action (with `to_call`/pot/stacks at decision time), hole cards, board,
payouts. Keep the in-memory deque only as a live tail.

### H9 — SDK "recent action history" is the first 200 events — **high**
`player_sdk/client.py:178-185`: `?offset=0&limit=200`. After ~13 hands the bot's
`action_history` stops updating (and mixes all earlier hands, with no hand
boundary since `hand_started` is dropped by `_history_from_events`). Any bot
doing opponent modelling from history gets stale/wrong data. It is also one
extra HTTP GET per turn (`_ws.py:172`).
Test: `test_h9_action_history_includes_the_latest_actions`.
Fix: have the server include the *current hand's* actions in `your_turn` (no
extra request, no stale data).

### M1 — Odd chip goes to the lowest seat index, not left of the button — **medium**
`game/showdown_resolver.py:58-63`. Winners keep seat order, so seat 0 collects
every odd chip. Standard rule: first winner clockwise from the button. Tiny but
systematic bias (and the engine's first-hand button is always seat 0).

### M2 — Mid-hand `end_match` destroys chips — **medium**
`game/game_service_core.py:497-528`. Confirmed: after a 100-raise/call and a
50-bet/call, ending the match leaves stacks `[850, 850]` (sum 1700 of 2000);
300 stays in `engine.pot`, and results report stacks only.
`refund_committed` refunds only the *current street's* bets
(`curr_bet_amount` is zeroed each street). `play_local_match` triggers this on
its duration limit. Fix: track per-hand contributions (needed for C1 anyway) and
refund by them; or finish/void the hand cleanly.

### M3 — Action event `amount` has three meanings — **medium**
`game/action_engine.py:114,147,177`: call → chips *added*; bet → bet *total*;
raise → raise-*to* total. Any consumer (replayer, SDK history, bot) must
special-case. Fix in the new hand-history schema: always emit `amount_added`
and `street_total`.

### M4 — WebSocket reconnect race and unclean exits — **medium**
`realtime_websocket_gateway.py:104-105`: on disconnect it calls
`connections.disconnect(player_id)`, which removes whichever socket is
registered — so an old socket closing *after* a reconnect de-registers the new
one and the bot stops receiving turns. (`ConnectionManager._disconnect_if_current`
already has the correct compare-and-pop; use it.) Non-dict / invalid JSON frames
raise out of the loop without cleanup (`:61-62`). A second connection with the
same key silently replaces the first.

### M5 — Bot exception kills the participant's own runner — **medium**
`player_sdk/_ws.py:178`, `client.py:220`: an exception in `act()` propagates and
terminates `play()`, after which H6 applies. Catch, log, and fall back to
check/fold (opt-in strict mode for local testing).

### M6 — Engine facts a bot needs are missing from the state — **medium**
`game/state_projection.py`: no dealer/button index or position, blind sizes,
starting stack, or per-hand history (see H9). `hand_started` carries
`dealer_index` but the SDK discards it.

### L — assorted
* Royal flush is labelled "Straight Flush" (`poker_hand_evaluator.py:106`) — cosmetic.
* `eliminate_busted_players` reuses `is_folded` for eliminated seats — works,
  but obscures intent (`runtime_flow.py:125-148`).
* `uvicorn.run(..., reload=True, host="0.0.0.0")` in `__main__`
  (`run_poker_server.py:11-15`).
* `current_actor_index` mutates `turn_index` as a side effect of a read
  (`runtime_flow.py:108-122`).
* API key accepted in WS query string (appears in access logs).

### Checked and found correct
Hand evaluation (wheel, steel wheel, two trips→full house, three pair, kicker
ordering, flush-over-straight, ties) — spot-checked, no defects; heads-up
button/SB/BB posting rules; blind capping for short stacks; min-raise
size tracking for normal raises; stale-`turn_id` rejection; chip conservation in
normal multi-hand play; button skipping busted seats.

> **Correction (added during Phase 2).** An earlier version of this list also
> said "postflop order" was correct. That was wrong: see **N1** in §9.

---

## 2. Robustness

| Scenario | Today | Severity |
|---|---|---|
| Bot crashes / disconnects | Server waits full timeout every turn, forever | high (H6) |
| Bot hangs in `act()` | Same; fallback = check-or-fold | high (H6) |
| Returns garbage / illegal action | Error reply, **match deadlocks** (C4); non-int amount crashes socket (H4) | critical |
| Raises in `act()` | Participant's runner exits (M5) → H6 | medium |
| Uses too much memory/CPU | Not enforced — bot runs on the participant's machine | n/a today |
| Reads other bots' cards/state | **Possible**: C3 unauthenticated `viewer_id` | critical |
| Isolation of bot code from engine | Total today (separate machines/processes) — but only because nothing is hosted | — |
| Server crash/restart | All matches and results lost (in-memory only) | medium |
| Compute fairness | Bots run on heterogeneous laptops; timeout includes network RTT | medium |

Note: if Phase 2 moves to organiser-hosted bots, *all* of the memory/CPU/
network/filesystem isolation is new work (containers, cgroups, no-network,
per-turn timeouts enforced by the runner).

## 3. Fairness and statistical validity

* **F1 (high) Not reproducible.** `random.shuffle` on the global RNG
  (`poker_deck.py:23`); a fresh `PokerDeck()` is built each hand
  (`poker_game.py:64`). No seed is stored anywhere, so no replays-from-seed, no
  audit, no re-runs.
* **F2 (high) Duplicate poker is feasible, with two changes.** (1) Seed per
  match and derive a per-hand deck seed (store in hand history). (2) Freeze-out
  matches diverge (different stacks → different action sequences), so duplicate
  needs *fixed-stack hands*: reset both stacks to N BB every hand and report
  bb/hand. Then a pair plays seed S as (A,B) and again as (B,A) and results are
  summed — typically removes most card-luck variance. ~Small change in
  `PokerGame.reset_hand` + a `reset_stacks_each_hand` match option.
* **F3 (high) Scoring by freeze-out winner is statistically weak.** Binary
  result with unlimited `max_hands`; a single all-in decides a 50 BB match. Use
  net chips (mbb/hand) over many fixed-stack hands with a confidence interval.
  Rough sizing *(assumes ~5 bb/hand SD — to be measured with the sample bots)*:
  ±0.1 bb/hand at 95% needs ≈(1.96·5/0.1)² ≈ 10k hands per matchup without
  variance reduction; duplicate typically cuts that several-fold.
* **F4 (medium) Position fairness.** Button rotates correctly each hand, but the
  first hand's button is always seat 0 (`player_ids[0]`) — with a capped or odd
  number of hands the first listed bot has a systematic edge. Randomise/alternate
  seat order per matchup (duplicate handles this automatically).
* **F5 (medium) Constant blinds, unbounded default length** (`max_hands=None`):
  two passive bots can run very long; one dead bot wastes minutes (H6). Always
  set `max_hands` (or fixed-stack hands) in tournament mode.
* **F6 (low)** Mersenne-Twister is fine for fairness here (bots can't observe
  it) but a per-match `secrets`-derived seed that is *logged* gives both
  unpredictability and reproducibility.

## 4. Inefficiencies

Measured (2 conservative bots, local, `max_hands=40`, effectively infinite stacks):

| Path | Throughput |
|---|---|
| Engine only, in-process (`GameService`) | ≈1,700 hands/s (~0.6 ms/hand) |
| Real match over WebSocket via `play()` | ≈5.9 hands/s (~170 ms/hand) |
| `play_local_match` (HTTP polling, 0.1 s poll) | tens of seconds for a short freeze-out (integration test: 32 s) |

So the engine is **~290× faster than the system around it**; the wall-clock is
transport, not poker. (Not yet profiled; from the code the likely costs are:
one extra `GET /events` per bot turn (`_ws.py:172`), per-action JSON +
broadcast to every player, 5 s idle recovery polls, and the harness'
`sleep(poll_interval)` + 3 requests per action.) Implications: a round robin of
T teams is T(T−1)/2 matchups; serial at ~6 hands/s, 20 teams × 2,000 hands ≈
380k hands ≈ 17 h — must be parallelised, or run engine+bots in-process (no
network) for the final.

* **Hand evaluator (~99 µs per 7-card eval)** — 21 combos × Counter/sort per
  combo; fine at this scale (not a hot path), only worth optimising if you do
  Monte-Carlo inside the harness.
* New 52-object deck + shuffle per hand (`poker_deck.py`, `poker_game.py:64`) —
  negligible (<0.1 ms) but trivially cacheable when seeding is added.
* Single process, single event loop, all matches share one GIL; fine for a few
  concurrent matches, not for CPU-heavy bots (which run elsewhere today).
* No process-per-hand spawning anywhere (the brief's concern doesn't apply: no
  bot subprocesses exist yet).

## 5. Areas for improvement

* **Tests (high):** `game/` rules have **no direct tests** — nothing for
  `action_engine`, `showdown_resolver`, evaluator, side pots, min-raise; no
  tests for server auth/routes or the WS gateway. **CI does not run pytest at
  all** (`.github/workflows/ci.yml` only runs ruff + `compileall`). Add a
  `pytest -m "not integration"` job.
* **Integration tests not hermetic (medium):** 2 of 3 fail on a clean checkout
  because the `admin` fixture needs `POKER_ADMIN_API_KEY`/`.env`
  (`tests/test_integration_local.py:25-33`); they pass with
  `POKER_ADMIN_API_KEY=admin-dev-key`. The harness and the fixture disagree on
  the default.
* **Developer experience (medium):** to test a bot a participant must pip-install,
  have the server auto-spawned, and bots are tested only against *themselves or
  the single example bot*; the local harness is slow and leaves players
  registered globally. Wanted: a one-command `local_runner` (in-process engine,
  no server) with several sample opponents, seeds, and a bb/hand + CI report.
* **Hand-history format (high, see H8):** define one schema now — it feeds the
  replayer, stats and disputes.
* **Logging (medium):** server logs are `logging.debug` only for socket drops;
  no structured per-match log; bot-side `print`s only. Needed: per-bot stdout/
  stderr capture (Phase 3 requirement) and server-side audit log.
* **Code structure (low):** engine is reasonably decomposed; the
  `runtime_flow`/`game_service_core` split passes control via tuples of 4 values
  and `Optional` events, which is where C2/H1 hide. Worth simplifying *when*
  fixing them, not before. Docs: README documents "side-pot-free" behaviour as a
  feature.
* **Persistence (medium):** nothing survives a restart (matches, players, keys
  rotated at runtime live only in `api_keys` dict).

---

## 6. Regression tests added

`tests/test_audit_regressions.py` — 12 strict-xfail tests, one or more per
Critical/High finding (C1×2, C2, C3, C4, H1, H2, H3, H4×2, H5, H9). Run
`pytest tests/test_audit_regressions.py --runxfail` to see them fail with the
real assertion. H6 (needs a forfeit policy), H7/F-series (design) and M-items
have no test yet.

## 7. Proposed fix order (nothing applied yet)

1. **Engine correctness:** C2+H1 (round-completion logic) → C1 (side pots +
   uncalled-bet return, per-hand contribution tracking) → H2 → H3 → M1/M2.
2. **Robustness:** C4 (validate-then-cancel) + H4 (input validation) → H6
   (forfeit policy) → M4/M5.
3. **Security:** C3 (authenticated, identity-derived views) → H5 (dotenv order,
   no default admin key).
4. **Fairness/data:** H7/F1/F2 (seeded decks, duplicate mode, fixed-stack hands)
   → H8 (append-only hand history) → H9/M6 (richer `your_turn`).
5. **Process:** run pytest in CI; make integration tests hermetic.

Items 1–3 are bug fixes I'd do regardless of competition design. Items 4–5
depend on the design chosen in Phase 2.

## 8. Open questions (needed before Phase 2)

1. **Game format** — your brief left `[heads-up / 6-max / both]` blank. Engine
   already supports N≥2; side pots matter for any format, multiway adds
   odd-chip/ordering cases and makes duplicate poker (seat-permutations) more
   expensive.
2. **Who runs the bots?** Today participants self-host. Your Phase 2/3 scope
   (upload page, build/validation status, team-private logs, sandboxing) implies
   *we* run them. That is a different architecture with much more work and
   risk in 7 h.
3. **Where it runs** — "laptop or HPC": HPC usually means no Docker (Apptainer/
   Singularity, SLURM), possibly no inbound network for a web UI.
4. **Team count and when final results must exist** — drives hands per matchup
   and parallelism (see §4).

---

## 9. Fix status (updated after Phase 2 implementation)

Scope decision: fix what the competition path (`arena/`) exercises; leave
server-only items for later. Each fix is its own commit and graduates its
`xfail` repro in `tests/test_audit_regressions.py`.

| Item | Status | Commit |
|---|---|---|
| C1 side pots / uncalled bet | **fixed** (+ `tests/test_showdown_pots.py`) | `07c5537` |
| M1 odd chip to first seat left of button | **fixed** | `07c5537` |
| C2 all-in raise answered | **fixed** | `decfc39` |
| H1 run-out when only one can act | **fixed** | `decfc39` |
| H2 all-in below min raise/bet | **fixed**; short all-in no longer lowers the raise increment | `d430546` |
| H3 BB-option raise | **fixed** (engine + SDK) | `0548a82` |
| H7 seeded deck | **fixed** (opt-in; server default unchanged) | `704c442` |
| M6 dealer/blinds in state | **fixed** (+ `GameState.is_dealer`) | `995f758` |
| H8 complete hand history | **addressed in the arena only**: `arena/table.py` records seeds, all hole cards, board and every action per hand. The server's bounded event log is unchanged | `020a981` |
| C3, C4, H4 (×2), H5, H6, H9, M2, M4, M5 | **open, deliberately** (server/SDK-network only; the competition does not use them). Their strict-xfail tests remain | — |

### Found after the audit

* **N1 (high) — wrong first actor after the flop** (`game_service_core.py`,
  `submit_action`). After a street advanced, the turn was overwritten with "seat
  after the player who just acted", so the **button acted first** postflop
  (heads-up: the small blind; multiway: the seat after the big blind) instead of
  last. This contradicted the "checked and correct" note in §1; that check was
  incomplete. Fixed in `15850c1` with tests in `tests/test_action_order.py`.
* **N2 (medium) — `min_raise_to` could exceed `max_raise_to`** after the H2
  fix, so `raise_to(min_raise_to)` faulted for short stacks. Found by running a
  20-bot field through the arena. Fixed in `cc08e16`.
* **N3 (medium) — agent teardown could raise under load** and fail a whole
  pairing (`proc.wait()` after `kill()` timed out with 21 workers). Fixed in
  `b7ac6ed`, plus one automatic retry on harness (not bot) errors.
* **Known simplification (low):** a short all-in raise still re-opens betting for
  players who already acted (real rules do not). Documented in the H2 commit.

### Fairness notes for the arena (F-series status)

* F1 seeding and F2 duplicate play: implemented (`arena/duel.py`). Each deal is
  played from both seats; a bot cannot carry memory from the first half to the
  mirrored deal because both bots are restarted between halves.
* Leaderboard statistics: mean bb/hand with Student-t CIs over deals; the
  ranking is flagged `~` where neighbours cannot be separated.
