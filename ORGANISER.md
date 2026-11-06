# Running the event (organiser guide)

This is the runbook for the organiser. Competitors read [README.md](README.md)
and [SUBMITTING.md](SUBMITTING.md).

The event in one paragraph: teams write a Python bot, pack it with
`python -m arena pack`, and upload the zip through a form. You download the
zips, import them, draw random groups of at most 8, and play Round 1 (a round
robin inside each group). The best 2 of each group play Round 2 (a round robin).
The final table decides the winner. Everything runs on your machine; there is no
network connection to the teams and no live leaderboard.

## 1. Read this first: safety and limits

State these plainly to yourself before you start.

* **Bots are not sandboxed.** Each bot runs as a child process under your user
  account, with your files, your network and your environment variables. A
  malicious or careless bot can read other teams' code (it is under
  `arena_data/`), delete files or use the network. The arena only enforces time
  and fault limits, not memory, CPU, files or network.
* **So run the event somewhere you can throw away**: a virtual machine or a
  container, or at the very least a separate user account on the laptop with no
  access to your own files and no saved credentials. The `Dockerfile` in this
  repository builds the old match server only (it copies `server/` and `game/`,
  not `arena/`), so it is not a ready-made sandbox for the event; you would
  have to write one. This guide does not claim the event is containerised.
* **Teams are trusted to follow the rules** (no network, no reading other files,
  no attacking the arena). Nothing enforces them. Read the response sheet and a
  few bots if you want more confidence.
* **The Google Form does not check files.** It only stores them. Teams must run
  `pack` first (the instructions say so); `import` re-checks every zip
  (see section 5).
* **Google Forms file upload needs every respondent to sign in to a Google
  account**, and it has no deadline setting other than closing the form by hand
  (section 4). Uploaded files count against the form owner's Drive storage.
* **A team can upload a zip packed under another team's name.** The newest zip
  for a name wins, so this could replace a real team's bot. The response sheet
  records who uploaded each file (verified email): look for a team name with
  more than one email before you import (section 4).
* **"Newest" is decided by the time written inside the zip** by the team's own
  computer when it ran `pack`. A team with a wrong clock can make an older zip
  look newer. Tell teams to pack again if in doubt.
* **Size limit:** 25 MB per bot, all files unzipped. This is enforced by `pack`
  and `import`; the form allows larger files (100 MB) so that the error comes from
  `pack`, not from Google.
* **Draw ends submissions.** After `tournament draw`, `import` still runs but a
  new or updated bot does not change who plays or which version plays.
* **Not part of the event:** the websocket gateway, self-registration and the
  GitHub-repository intake were built earlier and dropped. They are in git
  history (commits `1b1b94a` gateway, `cb39457` self-registration) and the older
  ladder code is described in [docs/legacy-server.md](docs/legacy-server.md).

## 2. The checklist

| When | What |
|---|---|
| Days before | Set up the machine (section 3), build the form (section 4), try the whole thing once with the example bots (section 11), tell teams which libraries are installed. |
| Before the deadline | Share the form link and the repository link. |
| At the deadline | Close the form. Download the files, `import`, check the output, `tournament status`. |
| After checking | `tournament draw`, `tournament start-groups`, leave `tournament run` going. |
| When status says `between` | `tournament start-finals`. |
| When status says `done` | The champion is printed. Publish (section 8). |

## 3. Set up the machine

Python 3.11 or newer, Git, and the repository:

```bash
git clone https://github.com/Manchester-AI-Society/poker_bot_infrastructure.git
cd poker_bot_infrastructure
python -m venv .venv
python -m pip install -r requirements.txt
```

(Activate the environment first: PowerShell `.venv\Scripts\Activate.ps1`,
macOS and Linux `source .venv/bin/activate`.)

The standard library and `requirements.txt` are what bots can use. If you
install anything else, tell the teams before they write their bots.

Check it works:

```bash
python -m arena validate bots/starter
```

```
OK: played 40 hands vs @call with no faults
```

## 4. The submission form (Google Forms, about 5 minutes)

Create a new form at forms.google.com and set it up as follows.

1. **Title:** `Submit your poker bot`.
2. **Description:** the repository link
   `https://github.com/Manchester-AI-Society/poker_bot_infrastructure` and the
   three commands teams run, one per line:
   `python -m arena validate bots/myteam`,
   `python -m arena match bots/myteam call --deals 200`,
   `python -m arena pack bots/myteam --team myteam`.
3. **Settings > Responses:** Collect email addresses = Verified. Allow response
   editing = off. Limit to 1 response = off (teams may resubmit; the newest
   working zip is played).
4. **Question 1:** `Team name`. Short answer, required. Response validation:
   Regular expression, Matches, `^[a-z0-9][a-z0-9_-]{0,31}$`. Custom error text:
   `Lowercase letters, digits, - and _ only, up to 32 characters; use the same name you gave to arena pack`.
5. **Question 2:** `Team members`. Paragraph, optional.
6. **Question 3:** `Your bot (the .zip from arena pack)`. File upload, required.
   Turn **off** "Allow only specific file types" (the list has no zip option).
   Maximum number of files: 1. Maximum file size: 100 MB.
7. **Confirmation message:** `Thanks. You can submit again until the deadline; the newest working upload is played.`
8. **At the deadline:** open the Responses tab and turn off Accepting responses.

Send the form link to the teams together with the repository link.

### Collecting the files

1. Open the form's response folder in Google Drive (Responses tab > View in
   Sheets > the linked folder, or the form's "File responses" folder in
   Drive).
2. Select everything and choose Download. Drive makes one zip of the folder.
3. Unzip it into a new folder called `downloads/` in the repository
   (git ignores it).

Drive adds the respondent's name to downloaded file names. That does not
matter: `import` reads the team name from inside each zip, and reads every
`.zip` it finds under the folder, including nested folders.

Before importing, open the response sheet and check that no team name appears
with two different email addresses. If one does, decide who owns the name and
delete the other person's zips from `downloads/`.

If Google is unavailable, any shared folder (Drive, Dropbox) or email works:
collect the zips into `downloads/` by hand.

## 5. Import

```bash
python -m arena import downloads
```

Real output from a rehearsal with a mixed folder (a stray text file named
`notes.zip`, a second team with identical code, a resubmission, and a broken
resubmission):

```
  REJECTED   (unknown team)       notes.zip: not a readable zip file: File is not a zip file
  UNCHANGED  tight-aggressive     tight-aggressive - Some Person.zip: identical code, no change
  SUPERSEDED starter              starter - Some Person.zip: replaced by this team's newer submission
  REJECTED   copycat              copycat - Other Person.zip: identical code was already submitted by 'starter'
  VALID      starter              starter - Some Person (1).zip: played 40 hands vs @call with no faults
  INVALID    push-fold            push-fold - Some Person (1).zip: AgentFault: ... act() must return a Response, but it returned str ('call'). ...
11 files read: 7 teams ready, 3 problem(s).
```

What each word means:

| Status | Meaning |
|---|---|
| `VALID` | The bot passed its check and is this team's current bot. |
| `UNCHANGED` | Same code as the team's current bot: nothing to do. |
| `SUPERSEDED` | The same team uploaded a newer working zip, which is the one played. |
| `INVALID` | The zip was readable but the bot fails its check (the reason follows). The team's previous working bot, if any, stays. |
| `REJECTED` | The file was refused: not a zip, an unsafe path, a link, too many or too big files (25 MB), a zip bomb, edited after packing (checksum mismatch), no `bot.py`, or identical code to another team. |

Each zip is treated as untrusted: nothing is run until the paths, sizes and
checksum have been checked, and every bot is validated again before it can
play. The command exits with code 1 when there is any `INVALID` or `REJECTED`
line; that is a prompt to look, not a failure.

You can run `import` as often as you like (for example once an hour, then once
more after the form closes). Re-importing the same folder is safe. Contact a
team whose bot is `INVALID`; they can upload a fixed zip before the deadline.
Check the roster:

```bash
python -m arena tournament status
```

```
phase: registration
teams with a working bot: 7
  adaptive
  equity-calc
  ...
```

To take a team out (a disqualification, a mistake) before the draw:

```bash
python -m arena tournament remove TEAM
```

State is kept under `arena_data/` (change the folder with `--root`).

## 6. Draw and play

Draw random, balanced groups of at most 8, with the best 2 of each group
advancing:

```bash
python -m arena tournament draw --group-size 8 --advance 2
```

```
drawn with seed 7 (the same seed gives the same draw); the best 2 of each group reach the finals
  group A: adaptive, the-rock, tight-aggressive
  group B: equity-calc, loose-aggressive, starter
```

The seed is printed; write it down. Add `--seed N` to repeat a draw, or
`--redo` to draw again (allowed until Round 1 starts). Drawing ends the
submission phase. For 20 teams and `--group-size 8` you get groups of 7, 7 and 6
(57 matches in Round 1) and 6 finalists (15 matches in Round 2).

Start Round 1 (100 deals per pairing is the default; each deal is two hands):

```bash
python -m arena tournament start-groups --deals 100
```

Sample output from a rehearsal with 6 teams, which used `--deals 200`:

```
round 1 started: 6 matches of 200 deals queued
```

Then, in a second window, start the player and leave it running. It plays
whatever is due and prints a line when something changes (sample from the same
rehearsal):

```bash
python -m arena tournament run
```

```
playing whatever is due; start-groups / start-finals in another window.
Press Ctrl+C to stop (matches in progress are replayed next time).
[tournament] group-1: adaptive vs the-rock
[02:04:02] groups | 6 teams | group: 0/6 played
[02:04:06] groups | 6 teams | group: 5/6 played
[tournament] phase is now 'between'
[02:04:07] between | 6 teams | group: 6/6 played
```

(`run` repeats its status line about once a second even when nothing has
changed, so the screen scrolls; that is harmless. The window you started
`start-groups` in is free for `tournament status`.)

Check progress at any time:

```bash
python -m arena tournament status
```

```
phase: between
teams with a working bot: 6
  ...
group A: adaptive, the-rock, tight-aggressive
group B: equity-calc, loose-aggressive, starter
group matches: {'done': 6}
finalists: adaptive, tight-aggressive, starter, equity-calc
```

When the phase is `between`, start Round 2 (200 deals is the default). The command
first prints a warning for any group where the last qualifying place is a
statistical tie:

```bash
python -m arena tournament start-finals --deals 200
```

Sample output from the rehearsal, which used `--deals 100`:

```
note: group A: tight-aggressive and the-rock are statistically tied for the last place
finals started: 6 matches of 100 deals queued
```

The best 2 by score go through regardless. If you want to settle a tie, use more
deals in Round 2 or play the close pairing again by hand. When the last final is
played the phase becomes `done`, `status` prints `champion: NAME`, and you can
press Ctrl+C in the `run` window.

### What `run` does

* Plays up to half your CPU count of matches at the same time (change with
  `--concurrency N`). Each match runs two bot processes.
* Enforces 1 s per move (`--move-timeout`), 20 faults (`--max-faults`) and 0.2 s
  of thinking per deal per half (`--think-budget`). These are the values teams
  were told; do not change them without telling teams.
* Cuts off a match that runs longer than `--time-cap` seconds (default 1800)
  after the deal in progress; it is scored on the deals it finished.
* Needs `start-groups` and `start-finals` to be run by you; it never moves a
  round on by itself except `between` and `done` when the last match ends.

### Sizing and timing

Measured here on a 22-core Windows machine with the example bots: 6 matches of
200 deals took about 6 seconds in total, and a pairing of 400 deals between
example bots took about 10 seconds. Real bots may be much slower. As a worst case
(an estimate, not a measurement): each bot may think for 0.2 s per deal per half,
which is about 80 seconds per 100-deal match for two bots that use their whole
budget. 57 such matches at 11 at a time is about 7 minutes. A laptop with 4 cores
plays 2 at a time and would take several times longer.

So plan by your hardware: time a rehearsal with the example bots (section 11),
multiply for slower bots, and choose `--deals` accordingly. More deals mean
tighter confidence intervals. Both rounds fit comfortably in a 7-hour event
for 20 teams at the default sizes unless many bots use their whole thinking
budget. If you stop early, results of unfinished rounds are never published.

## 7. Stopping and restarting safely

All state is on disk in `arena_data/` (one SQLite file, the imported bots, hand
histories, private logs).

* Stop `run` with Ctrl+C. A match that was in progress is thrown away and
  replayed from the start when you run it again. Finished matches are kept.
* If the machine or the process dies, run `python -m arena tournament run` again.
  This was tested: after the player was killed with 10 matches running, a new
  `run` played them again from the start.
* The draw and the phases are stored, so nothing needs repeating. Do not run two
  `run` commands at once on the same folder.
* If a match crashes with an error, `run` prints `[tournament] match N failed: ...`.
  Use Ctrl+C and start `run` again to retry the matches still queued; a bot that
  keeps crashing earns faults, it does not stop the event.

## 8. Publishing the website

The results website is a folder of static files made by `export`. Until a round
is complete it shows only the draw and the phase: no scores, no pairings, no
counts. Group tables appear when Round 1 is complete (phase `between`), and the
final table and the champion when Round 2 is (phase `done`). The page "How to
submit" is made from `SUBMITTING.md`.

Try it on your machine first:

```bash
python -m arena export --serve 8000 --loop 15
```

Open `http://localhost:8000/`. For a projector, open `http://localhost:8000/#/tv`.
Open it through the server, not by double-clicking `index.html`.

One export prints one line:

```
[export 02:04:51] updated: tournament done, 6 teams; published: 6 group matches, 6 final matches, 6 replays
```

Only the final's hand replays are published by default (`--replays all` or
`none` changes that; decide before the first push to a public host). Bot code,
tracebacks and logs are never published.

### Deploying on Vercel from a git repository

The site is static, so any static host works. With Vercel:

1. Create an empty repository on GitHub for the site, for example `poker-results`.
2. Clone it next to the arena repository: `git clone https://github.com/YOUR-ORG/poker-results.git arena_site`.
3. In Vercel, add a new project from that repository. Framework preset: Other.
   Leave the build command empty and the output directory at the repository root.
4. Make sure the git push works without a prompt (push once by hand from
   `arena_site` so your credentials are saved), and that the repository's branch
   is the one Vercel deploys.
5. Keep this running next to `run`:

```bash
python -m arena export --out arena_site --loop 30 --git-push
```

It re-exports every 30 seconds, commits and pushes only when the data changed
(an export that changes nothing writes nothing), and retries a failed push on
the next pass. Because nothing is published while a round is being played, the
site is redeployed at round boundaries, not once per match. The git mechanics
were tested here against a local repository (pushing to an empty clone worked);
the Vercel steps above were not tried from this machine.

Use `--title "Poker night"` for a page title.

## 9. Looking into a result

| Question | Where |
|---|---|
| Why did a team do badly? | Its fault count is in the group and final tables. Its private log, `arena_data/logs/TEAM/HASH/group-vs-OPPONENT.log` (and `final-vs-...`), holds what the bot printed and any crash output. The reason for each fault is stored in the match result (`fault_log_a`, `fault_log_b` in `arena.sqlite`) and on the action in the hand history (`fault`); there is no command to print it yet. |
| What happened in a hand? | `arena_data/hands/group-N.jsonl.gz`; see [ARCHITECTURE.md](ARCHITECTURE.md). |
| Who is in, which phase? | `python -m arena tournament status` |

## 10. Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `no .zip files under downloads` | The folder is empty or the path is wrong. Unzip the Drive download into it. |
| `REJECTED ... not a readable zip file` | The upload is not a zip (for example a renamed file or a half-finished upload). Ask the team to pack again. |
| `REJECTED ... edited after packing` | The zip's files do not match its checksum: it was changed after `pack`. Ask the team to pack and upload again. |
| `REJECTED ... identical code was already submitted by 'X'` | Two teams uploaded the same code. Decide who owns it and `tournament remove` the other, or ask for a different bot. |
| `INVALID ... act() must return a Response ...` | The bot returned something that is not a `Response` (for example the string `"call"`). The text names the fix. The team's older working bot, if any, still plays. |
| `cannot do that: at least two teams with a working bot are needed` | Import more bots first. |
| `cannot do that: already drawn; use --redo to draw again` | Add `--redo` (allowed until Round 1 starts). |
| `cannot do that: draw the groups first` | Run `tournament draw` before `start-groups`. |
| `cannot do that: the finals start once every group match is played` | Wait for `phase: between` in `tournament status`. |
| `cannot do that: teams can only be removed before the draw` | `remove` only works before the draw. |
| `nothing to run yet: import the submissions first` | `run` was started on a folder with no tournament; check `--root`. |
| A team is missing from the groups | Its zip was `INVALID` or `REJECTED`, or it arrived after the draw. Imports after the draw never change the groups. |
| The website shows no scores | By design until a round is complete. |
| `export` does not push | `arena_site` must be a git clone with a remote and saved credentials; see section 8. The error text from git is printed. |
| Others cannot open the site on your Wi-Fi | Use `--host 0.0.0.0`, allow Python through the firewall, and check the venue network lets devices reach each other. Or use the Vercel site. |

## 11. Rehearsal (do this once before the event)

You can rehearse the whole flow with the example bots in about a minute: see
"Run them as a small competition" in [bots/README.md](bots/README.md). It uses
the same commands as this guide, with folders that git ignores.

## 12. Command summary

```bash
python -m arena import downloads
python -m arena tournament status
python -m arena tournament remove TEAM
python -m arena tournament draw --group-size 8 --advance 2 [--seed N] [--redo]
python -m arena tournament start-groups --deals 100
python -m arena tournament run [--concurrency N] [--time-cap SECONDS]
python -m arena tournament start-finals --deals 200
python -m arena export --out arena_site --loop 30 --git-push
```

Every command takes `--root FOLDER` (default `arena_data`).
