"""Pulling team bots from the teams' own git repositories.

The organiser keeps a plain teams file, one line per team::

    # team   repository                                  branch (optional)
    alpha    https://github.com/alpha-team/poker-bot
    beta     https://github.com/beta-team/bot            dev

``sync`` clones each repository (shallow), and submits it the same way
``arena submit`` does: identical code is a no-op, a changed bot is validated
and only then replaces the team's current one, and a broken push never
removes a working bot. The outcome of every attempt is remembered per team,
so a wrong URL or a missing ``bot.py`` can be shown to the team instead of
failing silently.

The teams file is re-read on every pass, so teams can be added or corrected
while the event is running.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple
from urllib.parse import urlsplit

from .export import short_message
from .intake import BRANCH, TEAM_NAME, SubmissionError, submit
from .store import Store

ALLOWED_SCHEMES = ("https://",)
MAX_URL = 300


class TeamsFileError(Exception):
    """The teams file is missing or has lines that cannot be used."""


@dataclass(frozen=True)
class TeamSource:
    team: str
    url: str
    branch: Optional[str] = None
    line: int = 0


@dataclass(frozen=True)
class SyncResult:
    team: str
    # valid | unchanged | invalid | unreachable | rejected | error
    status: str
    digest: str
    message: str

    @property
    def ok(self) -> bool:
        return self.status in ("valid", "unchanged")


def _repo_key(url: str) -> str:
    """The same repository written two ways should compare equal."""
    key = url.lower().rstrip("/")
    return key.removesuffix(".git")


def parse_teams(
    text: str, *, allowed: Tuple[str, ...] = ALLOWED_SCHEMES
) -> List[TeamSource]:
    """Parses a teams file. Every problem is reported, with its line number.

    URLs are restricted (https only, no credentials) because they end up on a
    ``git clone`` command line and in logs.
    """
    sources: List[TeamSource] = []
    problems: List[str] = []
    teams: Dict[str, int] = {}
    repos: Dict[str, str] = {}

    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        parts = line.replace(",", " ").split()
        if len(parts) not in (2, 3):
            problems.append(
                f"line {number}: expected 'team repository-url [branch]'"
            )
            continue
        team, url = parts[0].lower(), parts[1]
        branch = parts[2] if len(parts) == 3 else None

        if not TEAM_NAME.match(team):
            problems.append(
                f"line {number}: team name '{team}' must be 1-32 characters "
                "of a-z, 0-9, '-' and '_'"
            )
        if team in teams:
            problems.append(
                f"line {number}: team '{team}' is already on "
                f"line {teams[team]}"
            )
        if not url.startswith(allowed):
            problems.append(
                f"line {number}: the repository must be an "
                f"{' or '.join(allowed)} URL"
            )
        elif len(url) > MAX_URL or "@" in urlsplit(url).netloc:
            problems.append(
                f"line {number}: the URL is too long or contains a login; "
                "use a public repository (never put a token in the URL)"
            )
        elif url.startswith("http") and not urlsplit(url).hostname:
            problems.append(f"line {number}: the URL has no host name")
        elif _repo_key(url) in repos:
            problems.append(
                f"line {number}: this repository is already used by "
                f"'{repos[_repo_key(url)]}'"
            )
        if branch is not None and not BRANCH.match(branch):
            problems.append(f"line {number}: '{branch}' is not a branch name")

        teams.setdefault(team, number)
        repos.setdefault(_repo_key(url), team)
        sources.append(TeamSource(team, url, branch, number))

    if problems:
        raise TeamsFileError("\n".join(problems))
    return sources


def load_teams(path: Path | str) -> List[TeamSource]:
    try:
        # utf-8-sig: Windows Notepad adds a byte-order mark.
        text = Path(path).read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise TeamsFileError(f"cannot read {path}: {exc}") from exc
    return parse_teams(text)


def condense(message: str) -> str:
    """The one line worth showing: git's 'fatal:' line, or the exception.

    Git ends its errors with advice ("and the repository exists."), and a
    validation failure is a whole traceback; neither last line is the point.
    Paths and long text are cut the same way as on the public site.
    """
    for line in message.splitlines():
        if line.strip().startswith(("fatal:", "error:")):
            return short_message(line)
    return short_message(message)


def sync_one(
    store: Store,
    source: TeamSource,
    *,
    move_timeout: float = 1.0,
    clone_timeout: float = 90.0,
) -> SyncResult:
    """Fetches and submits one team; never raises."""
    try:
        outcome = submit(
            store,
            source.team,
            source.url,
            branch=source.branch,
            move_timeout=move_timeout,
            clone_timeout=clone_timeout,
        )
    except SubmissionError as exc:
        message = str(exc)
        # A failed clone is a problem with the URL or the network; anything
        # else (no bot.py, copied code, too large) is a problem with the repo.
        status = (
            "unreachable" if message.startswith("git clone") else "rejected"
        )
        result = SyncResult(source.team, status, "", condense(message))
    except Exception as exc:  # a bad team must never stop the others
        result = SyncResult(
            source.team, "error", "", condense(f"{type(exc).__name__}: {exc}")
        )
    else:
        result = SyncResult(
            source.team,
            outcome.status,
            outcome.digest,
            condense(outcome.message),
        )
    try:
        store.set_sync_status(result.team, result.status, result.message)
    except Exception:  # remembering is best effort
        pass
    return result


def sync_teams(
    store: Store, sources: Sequence[TeamSource], **kwargs
) -> List[SyncResult]:
    return [sync_one(store, source, **kwargs) for source in sources]


class Reporter:
    """Turns sync results into log lines, only when something changed."""

    def __init__(self) -> None:
        self._last: Dict[str, Tuple[str, str, str]] = {}

    def lines(self, results: Sequence[SyncResult]) -> List[str]:
        out = []
        for result in results:
            key = (result.status, result.digest, result.message)
            first = result.team not in self._last
            if self._last.get(result.team) == key:
                continue
            self._last[result.team] = key
            if result.status == "unchanged" and not first:
                continue
            detail = result.message.strip().splitlines()[-1:] or [""]
            digest = f" {result.digest}" if result.digest else ""
            out.append(
                f"[sync] {result.team}: {result.status}{digest} - {detail[0]}"
            )
        return out


class TeamsFile:
    """The teams file, re-read on each use, keeping the last good version.

    An organiser editing the file mid-event may leave it half-written for a
    moment; that must not drop every team, so a bad edit is reported once and
    the previous list keeps being used.
    """

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self._good: Optional[List[TeamSource]] = None
        self._last_error: Optional[str] = None

    def current(
        self, report: Callable[[str], None] = print
    ) -> List[TeamSource]:
        try:
            self._good = load_teams(self.path)
            self._last_error = None
        except TeamsFileError as exc:
            if str(exc) != self._last_error:
                report(
                    f"[sync] {self.path} has problems; keeping the previous "
                    f"list:\n{exc}"
                )
                self._last_error = str(exc)
            if self._good is None:
                raise
        return list(self._good)


def run_loop(
    store: Store,
    teams: TeamsFile,
    interval: float,
    stop: threading.Event,
    *,
    report: Callable[[str], None] = print,
    reporter: Optional[Reporter] = None,
    **kwargs,
) -> None:
    """Syncs every ``interval`` seconds until ``stop`` is set."""
    reporter = reporter or Reporter()
    while not stop.is_set():
        try:
            sources = teams.current(report)
        except TeamsFileError as exc:
            report(f"[sync] cannot use the teams file: {exc}")
            sources = []
        for line in reporter.lines(sync_teams(store, sources, **kwargs)):
            report(line)
        stop.wait(interval)


def start_background(
    store: Store, teams: TeamsFile, interval: float, **kwargs
) -> threading.Event:
    """Runs ``run_loop`` on a daemon thread; set the returned event to stop."""
    stop = threading.Event()
    threading.Thread(
        target=run_loop,
        args=(store, teams, interval, stop),
        kwargs=kwargs,
        name="arena-sync",
        daemon=True,
    ).start()
    return stop
