# Running the event (organiser guide)

This is the runbook for the organiser. Competitors read [README.md](README.md)
and [SUBMITTING.md](SUBMITTING.md) (which is also the website's Info page).

The event is a **live knockout** played on a poker server that runs on your
laptop. Teams run their own bots on their own machines and connect to it over
websockets (through a Cloudflare tunnel, so it works on campus Wi-Fi). Teams
that cannot connect hand their bot in through a form and you play it for them.
A static website, hosted on Vercel, shows the play a few minutes behind the real
game.

```
teams' bots --(wss)--> Cloudflare tunnel --> poker server (your laptop)
                                                  |
                       backup zips --> arena backup-run (your laptop)
                                                  |
                                  arena live --> site repo --> Vercel website
```

## 1. Read this first: safety and limits

* **The server is reachable from the internet** while the tunnel runs. Anyone with
  the tunnel address and the **join code** can register a team and connect a bot,
  so give the code only to the teams. There is no limit on wrong join codes and no
  cap on registrations, so a longer code is safer than a short one.
* **Some server pages are public by design.** `/v1/tournament`, `/v1/lobby` and
  each match's `/v1/matches/<id>/events` need no key, so anyone with the tunnel
  address can watch tables in real time. The website is delayed on purpose; the
  server's own pages are not. Hole cards are not in those pages (only at a
  showdown), but the actions are. Do not share the tunnel address more widely than
  you must.
* **The admin key starts and resets the tournament.** `scripts/event.ps1` makes a
  random one and turns off the published dev keys. If you start the server some
  other way, set `ADMIN_API_KEYS` and `BOT_API_KEYS` yourself: leaving
  `BOT_API_KEYS` empty re-enables the dev keys (`dev-key-1`...).
* **Quick tunnels are best-effort.** Cloudflare can drop one (the log says `Tunnel
  not found`); a new one has a new address, so teams must be told, and the Info page's address
  only updates when the live feed restarts (run `down` then `up`).
* **Backup (zip) bots run on your machine without a sandbox.** They are the teams'
  code. Use a throwaway VM or a separate user account if you can.
* **Vercel's free plan allows about 100 deployments a day.** The live feed
  publishes every 5 minutes by default (about 84 over 7 hours) and only when
  something changed. Do not go below 60 seconds.
* **A server restart wipes everything held in memory**: keys, the lobby and the
  tournament. Teams register again (their names are free again).
* **State is in memory**: one tournament per server process.

## 2. The checklist

1. Python 3.11+, the repo, and its dependencies (section 3).
2. `cloudflared.exe` in `tools\` (section 3).
3. The site repo cloned on this machine with credentials saved (section 6).
4. The backup submission form made (section 4). Optional: the team-name
   registration form.
5. A rehearsal done at least once (section 10).
6. On the day: `up`, share the address and code, watch the lobby, import any
   backups, `start`.

## 3. Set up the machine

```powershell
git clone https://github.com/Manchester-AI-Society/poker_bot_infrastructure.git
cd poker_bot_infrastructure
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m pip install -e .
```

**cloudflared.** Download `cloudflared-windows-amd64.exe` from the cloudflared
releases on GitHub (<https://github.com/cloudflare/cloudflared/releases>), check
its SHA-256 against the value in the release notes (`Get-FileHash`), and save it
as `tools\cloudflared.exe`. The tested version is 2024.12.2. It needs no account.

**Docker/macOS route.** Ammar's `scripts/event.sh` does the same with Docker (see
[docs/running-an-event.md](docs/running-an-event.md)). On networks that intercept
HTTPS add `TUNNEL_PROTOCOL=quic` to `.env`.

### Which tunnel protocol

| Protocol | Uses | Works when |
|---|---|---|
| `quic` (this script's default) | UDP 7844 | UDP is allowed, and also when the network intercepts HTTPS |
| `http2` | TCP 443 | UDP is blocked and HTTPS is not intercepted |

On the development laptop's student Wi-Fi, `http2` failed with `x509: certificate
signed by unknown authority` and `quic` worked. If `up` says the tunnel did not
connect, try the other one (`-Protocol http2`), or put the laptop on a phone
hotspot.

## 4. The forms

### The backup submission form (Google Forms, about 5 minutes)

Create a new form at forms.google.com:

1. **Title:** `Backup: submit your poker bot`.
2. **Description:** `Only use this if you cannot connect to the live server. Pack
   your bot with: python -m arena pack bots/myteam --team myteam, then upload
   myteam.zip. Use the same team name as on the website.`
3. **Settings > Responses:** Collect email addresses = Verified. Allow response
   editing = off. Limit to 1 response = off (teams may resubmit; the newest
   working zip is used).
4. **Question 1:** `Team name`. Short answer, required. Response validation:
   Regular expression, Matches, `^[a-z0-9][a-z0-9_-]{0,31}$`.
5. **Question 2:** `Team members`. Paragraph, optional.
6. **Question 3:** `Your bot (the .zip from arena pack)`. File upload, required.
   Turn **off** "Allow only specific file types" (the list has no zip option).
   Maximum number of files: 1. Maximum file size: 100 MB.
7. **At the deadline:** Responses tab, turn off Accepting responses.

Pass the form's link to the live feed as `-FormUrl` (section 5) so the Info page
shows it. Respondents need a Google account. The form cannot check the files:
`pack` does that on the team's machine and `import` checks again.

### Optional: a team-name registration form

Teams can register just a name on the website so they are listed straight away
(`registered`, then `in the lobby`, `playing`, `out`, `champion`). It is only a
listing. Skip this if you do not want it: the site then has no Register page.

Make a second Google Form: title `Register your team name`; do **not** collect
email addresses (its sheet is published); one required short-answer question
`Team name` with the same regular expression as above. Then:

1. In the form editor open the three-dots menu, choose Get pre-filled link, type
   `x` in Team name, Get link, copy it, and delete the final `x` so it ends in
   `entry.123456789=`. That is `-RegisterForm`.
2. Responses > Link to Sheets; in the sheet, File > Share > Publish to web, pick
   the responses tab, choose Comma-separated values (.csv), Publish, and copy the
   address. That is `-Registrations`. It makes the sheet public, which is why the
   form must not collect emails.

## 5. Start the event

```powershell
.\scripts\event.ps1 up `
  -Site "D:\code repos\poker-arena-site" -GitPush `
  -FormUrl "https://forms.gle/YOUR-BACKUP-FORM" `
  -RegisterForm "https://docs.google.com/forms/d/e/FORM_ID/viewform?usp=pp_url&entry.123456789=" `
  -Registrations "https://docs.google.com/spreadsheets/d/e/.../pub?output=csv"
```

`up` starts the poker server (with a fresh admin key and join code, kept in
`.event\event.env`, which git ignores), the Cloudflare tunnel, and the live feed
for the website, then prints:

```
Server (this PC):  http://127.0.0.1:8000
Public address:    https://something-random.trycloudflare.com
Join code:         d6722e
Admin key:         ...   (keep private)
```

Options: `-Protocol quic|http2`, `-Cloudflared PATH`, `-NoTunnel`, `-Delay 360`
(seconds the site runs behind the game), `-Interval 300` (seconds between
publications), `-HideCode` (keep the join code off the Info page; it is shown by
default), `-Port 8000`. Other commands: `status`, `url`, `start`, `down`.

The Info page shows the public address and the join code, and tells people how
to register and connect. Anyone who finds the site's address can therefore
register a bot; pass `-HideCode` and read the code out in the room if you do not
want that.

## 6. The website on Vercel

The site is the static folder the live feed writes. Point it at a git clone of the
site repository (for example `D:\code repos\poker-arena-site`, deployed by Vercel
on every push) and pass `-GitPush`. The first publication also copies the site's
pages; after that it publishes only when something changed. Check the clone can
push without a password prompt (`git push` once by hand). The site shows:

* the lobby and registered teams before the start;
* each round's tables with chips, hands played and winners;
* a table viewer that replays hands at a watchable pace, **behind the real game by
  `-Delay` seconds**, with cards face up only at a showdown;
* the champion once the delayed view reaches the end of the final;
* the Info page (how to join, with the address and form link).

## 7. During the event

1. **Share** the public address and join code with the teams.
2. **Watch the lobby:** `.\scripts\event.ps1 status` (or the Teams page).
   Only bots connected **when you start** get a seat.
3. **Backups.** Download the backup form's files (Responses > the linked Drive
   folder > Download), unzip them into `downloads\`, then import and run them:

   ```powershell
   python -m arena import downloads
   .\scripts\event.ps1 backups
   ```

   `import` checks every zip and prints `VALID`, `INVALID`, `REJECTED` or
   `SUPERSEDED` per file. `backups` (which runs `arena backup-run`) makes each imported team a player and
   starts its bot as a websocket client, **only for teams not already connected
   live** (add `-All` to run everyone, `-TakeOver` to replace the key of a name that is
   already a player). Leave it running in its own window: it restarts a
   crashed bot a few times and stops when the tournament finishes.
4. **Start** when the lobby looks complete:

   ```powershell
   .\scripts\event.ps1 start
   ```

   Round 1 puts everyone on tables of up to 23; table winners play the final.
   Blinds double every 10 hands; a table reaching 500 hands sends its chip leader
   on. (Edit the numbers in `scripts\event.ps1` or POST your own to
   `/v1/tournament/start`.)
5. **Follow it** on the website (a few minutes behind) or with
   `Invoke-RestMethod http://127.0.0.1:8000/v1/tournament`.
6. **Afterwards:** `.\scripts\event.ps1 down`.

## 8. Troubleshooting

| Problem | What to do |
|---|---|
| `up` says the tunnel did not connect | Read `.event\tunnel.log`. `x509 ... unknown authority`: use `-Protocol quic`. Timeouts on `quic`: UDP is blocked, use `-Protocol http2`. Or use a phone hotspot. |
| The public address gives `530` | The tunnel is not connected (same causes), or Cloudflare dropped it: run `down` and `up` again; the address changes, so tell the teams. |
| A team gets `401` | A typo, or the server was restarted: they register again. |
| A team gets `403` when registering | The join code is wrong. |
| A team cannot reach the address | They must use it exactly as shown (`https://`, no `:8000`). Opening `/health` should show `{"ok":true}`. |
| `backup-run` says a name is already a player | The team registered live earlier but is not connected. If they should be run for them, add `--take-over`. |
| `start` says at least 2 bots must be in the lobby | Wait for teams to connect, or run `backup-run`. |
| The site shows nothing | It is behind by `-Delay` seconds on purpose and updates every `-Interval` seconds. Check `.event\live.log`; a push error is printed there. |
| The site stopped updating | Check `.event\live.log` (the server may have restarted; the feed carries on by itself) and that `git push` works in the site folder. |
| A bot crashes in the middle of a game | Nothing to do: it plays a safe move (check, or fold) and the turn timer covers it. |

## 9. Sizing

On this machine a 10-bot tournament through the real websockets finished in under
a minute with the example bots, and slower networks or slower bots take
proportionally longer. Each table is one match on the server; tables run in
parallel. The server keeps each table's whole event log in memory (100,000 events
per table).

## 10. Rehearsal (do this once before the event)

```powershell
.\scripts\event.ps1 up -NoTunnel -Port 8010
$env:POKER_ADMIN_API_KEY = (Get-Content .event\event.env | Select-String ADMIN_KEY).Line.Split('=')[1]
$env:POKER_SERVER_URL = "http://127.0.0.1:8010"
python examples\bots\remote\simulate_devices.py --bots 10
.\scripts\event.ps1 down -Port 8010
```

Ten example bots, each in its own process, register, join and play a tournament.
Expect `status: finished  champion: ...`. To rehearse the website too, add
`-Site "<a scratch folder>"` to `up` and preview that folder with
`python -c "from arena import serve; s=serve.make_server(r'<folder>','127.0.0.1',8080); s.serve_forever()"`
(then open `http://127.0.0.1:8080`). Rehearse the backup path by packing and
importing an example bot (`python -m arena pack bots\starter --team starter`),
then `.\scripts\event.ps1 backups` before starting.

## 11. Command summary

```powershell
.\scripts\event.ps1 up -Site <folder> -GitPush [-FormUrl ..] [-RegisterForm ..] [-Registrations ..]
.\scripts\event.ps1 status
.\scripts\event.ps1 start
.\scripts\event.ps1 down
python -m arena import downloads                      # check backup zips
.\scripts\event.ps1 backups                            # play them for teams not connected
python -m arena live --server http://127.0.0.1:8000 --out <site> --once   # publish once
```

The older modes (a heads-up duplicate round robin with groups, and the zip-only
flow) still exist in the code (`arena tournament ...`) but are not part of this
event.
