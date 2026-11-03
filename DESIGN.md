# Phase 2: competition design

Assumptions (from the brief and the Phase 1 answers; change any of them and
the numbers below change with them):

- Heads-up no-limit Hold'em, Python bots, 7-hour hackathon, about 20 teams.
- Bots arrive as a file or git repo. **The organiser runs every bot** on one
  machine (laptop or HPC node). Participants do not host anything.
- Final results must exist at the end of the event.
- Measured on this machine: engine ~1,700 hands/s in-process; a subprocess
  JSON-lines round trip costs ~36 us per decision. So the harness is cheap and
  **bot think time is the real compute cost**.

## 1. Three designs

### A. Offline round robin after a deadline

Teams drop bots in `bots/<team>/`. After the deadline the organiser runs
`arena run` once: every pair plays N duplicate deals, results are ranked.

- **Participant experience:** blind until the end. They test with the local
  runner (`arena match mybot.py starter.py`) and have no signal on how they
  rank. Weakest feedback loop, and the most last-minute surprises.
- **Scoring:** mean bb/hand against the field, with a 95% CI.
- **Variance:** duplicate deals (each seeded deal played from both seats),
  fixed 100 bb stacks reset every hand, thousands of hands per pairing.
- **Compute:** 190 pairings x 2,000 hands = 380k hands. About 6-7 min of
  harness time on one core with instant bots; with bots at ~5 ms/decision
  (~50 ms/hand) it is ~5 core-hours, i.e. ~40 min on 8 cores.
- **Security:** bots run as the organiser's user in subprocesses.
- **Failure handling:** see section 3 (shared by all designs).
- **Build complexity:** small. About 2-3 h including the engine fixes.

### B. Continuous live ladder

Same runner, but a scheduler runs matches continuously while teams keep
submitting new versions. Leaderboard updates throughout the day.

- **Participant experience:** best. They submit, get validated, and see their
  rank move within minutes.
- **Scoring:** Elo/TrueSkill is the usual choice for a ladder, but with only
  ~20 heads-up bots the full pairwise matrix is cheap, so a better option is
  the *always-current round robin*: keep one result per pair for the latest
  version of each bot, and recompute only the 19 pairings that involve a
  changed bot (~19 x 2,000 = 38k hands, about 40 s with fast bots). Scores
  are still mean bb/hand with CIs, with no Elo noise or ordering effects.
- **Variance:** same as A, plus staleness: results are only comparable between
  the versions that played. Each result row stores both bot hashes.
- **Compute:** continuous load all day. Roughly 2-3x A in total hands, because
  of re-runs after each new version.
- **Security:** same as A, but untrusted code now runs *all day* on the same
  machine, so a bot that eats memory affects everyone.
- **Failure handling:** needs a quarantine path (a bot that fails validation or
  faults repeatedly is skipped until it is resubmitted).
- **Build complexity:** medium. Needs a scheduler loop, versioning, a
  validator, and a "latest version" rule. About 4-5 h.

### C. Hybrid: live ladder, then a frozen final round robin

B during the event for feedback. At the deadline, freeze the submissions
(record content hashes), then run A on exactly those versions with a larger N.
The final ranking comes only from the frozen run.

- **Participant experience:** B's feedback, plus a clean final that is not
  affected by last-minute version churn or an overloaded scheduler.
- **Scoring:** ladder = incremental bb/hand (labelled "provisional"); final =
  bb/hand across the full duplicate round robin, with CIs.
- **Variance:** the ladder is noisy by design (fewer hands); the final uses
  more hands and can add a tie-break stage (more deals for pairs whose CIs
  overlap near the podium).
- **Compute:** B's load plus one A run at the end (~6-40 min).
- **Security:** same as B, but the final runs after everyone has stopped
  submitting, so it can be run on a clean/isolated machine or an HPC node.
- **Failure handling:** as B, plus a pre-final re-validation of every frozen
  bot.
- **Build complexity:** medium. C is B plus a small `freeze` command; the final
  run is just A. About 5 h, but the build order puts A first, so you can
  stop at any point and still have a working competition.

### Comparison

| | A offline | B live ladder | C hybrid |
|---|---|---|---|
| Feedback to teams | none | continuous | continuous |
| Final-result trustworthiness | high | medium (moving target) | high (frozen) |
| Build effort | S (2-3 h) | M (4-5 h) | M (5 h, A first) |
| Extra risk | last-minute bot failures | scheduler / resource contention | same as B, contained by freeze |
| Fits 7 h event | yes | yes | yes |

## 2. Recommendation: C, built in the order A -> ladder -> freeze

Reasons: teams get feedback they will actually use over 7 hours, the final
result is not at the mercy of a half-finished ladder, and because the ladder
is just the same runner re-invoked on changed bots, the extra cost over A is
the scheduler plus the validator, not a second system. If time runs short,
you ship A and still have a legitimate competition.

Scoring decision: **mean bb/hand against the field (with 95% CI), not
Elo/TrueSkill.** It is what is used in published computer-poker competitions,
it needs no ordering assumptions, and with a full round robin it is exactly
computable. Pairwise win/loss records are shown as a secondary column and
tie-break. Total chips against the field rewards exploiting weak bots, which
is a feature of the format, so I will keep it unless you want a
"beat-everyone" variant.

## 3. Shared behaviour

**Failures (all designs).** An invalid action or move timeout becomes
check-if-legal else fold, and is logged to the team's private log. The bot
process is killed and respawned on a timeout. After K faults (default 20) in a
pairing, the bot is replaced by an always-fold stub for the rest of that
pairing and the fault is flagged on the leaderboard. Folding every hand costs
~0.75 bb/hand, so failures are naturally penalised without special-casing
scores. A bot that cannot import or fails the smoke match is `INVALID` and
never enters a pairing.

**Time limits.** Per-move hard limit (default 1 s, configurable); per-pairing
wall-clock cap. Bots are CPU-bound, so one bot process per core.

**Dependencies.** Teams run against one shared virtualenv (numpy etc.
installed by the organiser). Per-bot installs are out of scope for 7 hours.

**Security.** Subprocess per bot, stdout reserved for the protocol (a bot's
prints go to its private log), time limits, and on Linux/HPC optional
`resource.setrlimit` for memory. This is not a sandbox. Teams are at a
hackathon and trusted by assumption; if that is wrong, the next step is
Docker or bubblewrap, not more Python.

## 4. Architecture

```
 bots/<team>/            ┌───────────────────────────────────────────┐
  bot.py  (file / git)   │ arena (one Python package, one CLI)       │
        │                │                                           │
        ▼                │  validator ──► jobs table (SQLite)        │
 intake (CLI/watch dir)  │                    │                      │
  - hash content         │   scheduler: "latest version vs every     │
  - store version        │   other latest version", re-queue on      │
  - validate (import +   │   new hash                                │
    smoke match)         │                    ▼                      │
        │                │      worker pool (processes)              │
        ▼                │       └─ Engine (in-proc, seeded deals)   │
  versions table ───────►│            ├─ BotHost A (subprocess)      │
                         │            └─ BotHost B (subprocess)      │
                         │                    │                      │
                         │                    ▼                      │
                         │    results (SQLite)   hands/<job>.jsonl.gz│
                         └─────────┬─────────────────────────────────┘
                                   ▼
                 leaderboard.json + per-match data ──► frontend (Phase 3)
```

- **Bot protocol:** the existing `PokerBot.act(GameState) -> Action`
  interface is kept, so the starter bot and current SDK models are reused. A
  host script runs the bot and speaks JSON lines over stdin/stdout:
  `{"type":"act","state":{...}}` -> `{"action":"raise","amount":300}`. State
  includes dealer, blinds, stacks, board, hole cards, legal actions and the
  full action history for the hand.
- **Submission/versioning:** a version is the content hash of the bot
  directory. Each team has one *current* version; old versions are kept. The
  ladder always plays current versions. `freeze` records the hashes used for
  the final.
- **Job queue/scheduler:** a `jobs` table in SQLite (pair, both hashes, seed,
  deals, status). Workers claim rows atomically. No Redis or Celery.
- **Results storage:** SQLite (`versions`, `jobs`, `results`, `faults`).
  Works on a laptop and on an HPC node; on SLURM, each task claims jobs from
  the shared DB file or runs one pairing from an array index.
- **Hand histories:** one gzip JSONL per job: seed, deal index, seat
  assignment, hole cards, board, every action, result in bb. A hand can be
  replayed exactly from the seed, so the Phase 3 replayer needs no extra
  state.
- **Local test runner:** `arena match a.py b.py --deals 200` runs the same
  code path as the competition, with no database. This is the participants'
  main tool.
- **Existing server:** the FastAPI server and `player_sdk` network client stay
  in the repo, but are out of the competition path. Their open findings are
  deferred (below) and the README will say server mode is not for the
  competition.

## 5. Phase 1 fixes in scope

Approved by delegation; the scope is the engine/rules bugs that the arena
exercises, plus what duplicate poker needs. Each fix removes its own
`xfail(strict=True)` marker.

| In scope | Why |
|---|---|
| C1 side pots / return uncalled bet | wrong results from hand 1 with unequal stacks and any all-in |
| C2 all-in raise must be answered | shoving is broken today |
| H1 only-one-can-act run-out | follows from C1/C2 |
| H2 short-stack shove below min-raise | illegal-action false positive |
| H3 BB option raise | SDK bots cannot raise from the BB |
| H7 seeded deck | duplicate poker and reproducibility |
| H8 complete hand history | replayer and disputes |
| M1 odd-chip rule | correct split pots |
| M6 dealer/blinds in state | bots need positions |

Deferred (server-only; tests stay as strict xfails): C3, C4, H4, H5, H6, M2,
M4, M5, H9. If you decide to also keep the live server path, they come back
into scope.

## 6. Defaults I will use unless told otherwise

- 100 bb stacks, 10/20 blinds, stacks reset every hand.
- Ladder: 200 deals per pairing (400 hands). Final: 1,000 deals (2,000
  hands), extra deals for close podium pairs.
- Hard move limit 1 s; 20 faults before the always-fold stub.
- Provisional ladder and final ranking both use mean bb/hand with 95% CI.
- Per-hand variance will be measured on the fixed engine before the hand
  counts are locked in; the numbers above are placeholders.
