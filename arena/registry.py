"""Team registration through GitHub issues.

The results site has a Register page. It checks a team's name and repository
address and opens a pre-filled issue in a public *registry* repository; the
team presses "Submit new issue" while signed in to GitHub. The arena reads
those issues and turns the valid ones into teams to pull, exactly as if they
were lines in a teams file.

Why issues, and not a form that posts to a server:

* Nothing to run or secure. GitHub keeps the data, rate-limits the spam and
  needs an account to post, and an issue's author cannot be forged.
* **Ownership is proven.** A registration is only accepted when the GitHub
  account that opened the issue owns the repository it names
  (``github.com/<owner>/...``), so nobody can register somebody else's repo.
* **Approval.** A registered repository is run on the organiser's computer
  with no sandbox, so a registration only counts once the organiser adds the
  ``approved`` label (only people with access to the registry can add labels),
  unless open registration is switched on. A ``verified`` label also overrides
  the ownership check, for repositories owned by an organisation.

Rules applied to every open registration issue, oldest first:

* team names are first come, first served and stay with the account that
  claimed them, even if an issue is later edited;
* one team per GitHub account (``max_per_user``), against spam;
* one team per repository;
* closing the issue withdraws the registration.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple
from urllib.parse import urlsplit

from .intake import BRANCH, TEAM_NAME
from .store import Store
from .sync import MAX_URL, TeamSource, _repo_key

NO_RESPONSE = "_No response_"
GITHUB_REPO = re.compile(
    r"^https://github\.com/([A-Za-z0-9-]+)/([\w.-]+?)(?:\.git)?/?$"
)
_SECTION = re.compile(r"^###\s+(.+?)\s*$", re.MULTILINE)

FIELDS = {
    "team name": "team",
    "repository url": "repo",
    "branch (optional)": "branch",
    "branch": "branch",
}


@dataclass(frozen=True)
class Registration:
    """One registration issue, as the form filled it in."""

    issue: int
    user: str
    team: str
    repo: str
    branch: Optional[str]
    labels: Tuple[str, ...]


@dataclass(frozen=True)
class Decision:
    registration: Registration
    status: str  # accepted | pending | rejected
    reason: str = ""

    @property
    def source(self) -> TeamSource:
        r = self.registration
        return TeamSource(r.team, r.repo, r.branch, r.issue)


def parse_body(body: str) -> Optional[Dict[str, str]]:
    """Reads the sections of an issue-form body; None if it is not ours."""
    pieces = _SECTION.split(body or "")
    # split gives [text before, title1, text1, title2, text2, ...]
    values: Dict[str, str] = {}
    for title, text in zip(pieces[1::2], pieces[2::2]):
        key = FIELDS.get(title.strip().lower())
        if key:
            value = text.strip()
            values[key] = "" if value == NO_RESPONSE else value
    if "team" not in values or "repo" not in values:
        return None
    return values


def parse_issue(issue: Dict[str, Any]) -> Optional[Registration]:
    """A Registration from a GitHub issue payload, or None for other issues."""
    if issue.get("pull_request") is not None:
        return None
    values = parse_body(issue.get("body") or "")
    if values is None:
        return None
    user = ((issue.get("user") or {}).get("login") or "").strip()
    labels = tuple(
        str(label.get("name", "")).lower()
        for label in issue.get("labels") or []
    )
    return Registration(
        issue=int(issue["number"]),
        user=user,
        team=values["team"].strip().lower(),
        repo=values["repo"].strip(),
        branch=values.get("branch", "").strip() or None,
        labels=labels,
    )


def problems(reg: Registration) -> Optional[str]:
    """The first thing wrong with the registration itself, or None."""
    if not TEAM_NAME.match(reg.team):
        return (
            "team name must be 1-32 characters of a-z, 0-9, '-' and '_' "
            f"(got {reg.team!r})"
        )
    match = GITHUB_REPO.match(reg.repo)
    if (
        not match
        or len(reg.repo) > MAX_URL
        or "@" in urlsplit(reg.repo).netloc
    ):
        return (
            "the repository must be a public "
            "https://github.com/<owner>/<name> "
            "address, with no password or token in it"
        )
    if reg.branch is not None and not BRANCH.match(reg.branch):
        return f"{reg.branch!r} is not a branch name"
    return None


def owner_of(repo: str) -> str:
    match = GITHUB_REPO.match(repo)
    return match.group(1).lower() if match else ""


def decide(
    registrations: Sequence[Registration],
    store: Store,
    *,
    open_registration: bool = False,
    max_per_user: int = 1,
) -> List[Decision]:
    """Accepts, holds or rejects each registration. Oldest issue first.

    Team names stay with the account that first had one accepted (kept in the
    store), so editing an old issue cannot take a name that another team holds.
    """
    decisions: List[Decision] = []
    taken_teams: Dict[str, str] = {}  # team -> user, within this pass
    taken_repos: Dict[str, str] = {}  # repository -> team

    for reg in sorted(registrations, key=lambda r: r.issue):

        def reject(reason: str) -> None:
            decisions.append(Decision(reg, "rejected", reason))

        wrong = problems(reg)
        if wrong:
            reject(wrong)
            continue
        verified = "verified" in reg.labels
        if owner_of(reg.repo) != reg.user.lower() and not verified:
            reject(
                f"the repository belongs to '{owner_of(reg.repo)}' but this "
                f"issue was opened by '{reg.user}'. Register from the account "
                "that owns the repository (for an organisation's repository "
                "the organiser can add the 'verified' label)"
            )
            continue
        claim = store.team_claim(reg.team)
        if claim and claim["user"].lower() != reg.user.lower():
            reject(
                f"the team name '{reg.team}' already belongs to "
                f"'{claim['user']}'"
            )
            continue
        if taken_teams.get(reg.team, reg.user).lower() != reg.user.lower():
            reject(f"the team name '{reg.team}' is already taken")
            continue
        key = _repo_key(reg.repo)
        if key in taken_repos and taken_repos[key] != reg.team:
            reject(
                f"this repository is already registered by "
                f"'{taken_repos[key]}'"
            )
            continue
        # The same account may re-register (to change the repository) but only
        # ever holds max_per_user different teams.
        mine = {
            d.registration.team
            for d in decisions
            if d.status != "rejected"
            and d.registration.user.lower() == reg.user.lower()
        }
        if reg.team not in mine and len(mine) >= max_per_user:
            reject(
                f"one account may register {max_per_user} team"
                f"{'' if max_per_user == 1 else 's'} (this one already has "
                f"{', '.join(sorted(mine))})"
            )
            continue
        # A later issue by the same account for the same team replaces the
        # earlier one (that is how a team changes its repository).
        decisions[:] = [
            d
            for d in decisions
            if not (d.status != "rejected" and d.registration.team == reg.team)
        ]
        taken_teams[reg.team] = reg.user
        taken_repos[key] = reg.team
        if open_registration or "approved" in reg.labels:
            decisions.append(Decision(reg, "accepted"))
        else:
            decisions.append(
                Decision(
                    reg, "pending", "waiting for the organiser's approval"
                )
            )
    decisions.sort(key=lambda d: d.registration.issue)
    return decisions


# -- talking to GitHub ---------------------------------------------------


class GitHubError(Exception):
    pass


class GitHubIssues:
    """Reads (and comments on) the issues of one repository.

    Uses the ``gh`` command line when it is installed and signed in (that
    carries the organiser's login, so reading is not rate-limited and
    commenting works). Otherwise it reads anonymously over the web, which
    GitHub limits to 60 calls an hour, so unchanged answers are not
    re-downloaded (an ETag makes a repeat call free).
    """

    def __init__(self, repo: str, *, token: Optional[str] = None) -> None:
        if not re.match(r"^[\w.-]+/[\w.-]+$", repo):
            raise GitHubError(
                f"registry must look like OWNER/REPO, not {repo!r}"
            )
        self.repo = repo
        self.token = (
            token
            or os.environ.get("GITHUB_TOKEN")
            or os.environ.get("GH_TOKEN")
        )
        self._etag: Optional[str] = None
        self._cache: List[Dict[str, Any]] = []

    @staticmethod
    def _gh_ready() -> bool:
        return shutil.which("gh") is not None

    def issues(self) -> List[Dict[str, Any]]:
        """Every open issue (not pull request) of the registry."""
        if self._gh_ready() and not self.token:
            return self._via_gh()
        return self._via_http()

    def _via_gh(self) -> List[Dict[str, Any]]:
        done = subprocess.run(
            [
                "gh",
                "api",
                "--paginate",
                "--slurp",
                f"repos/{self.repo}/issues?state=open&per_page=100",
            ],
            capture_output=True,
            text=True,
            timeout=60,
            stdin=subprocess.DEVNULL,
        )
        if done.returncode != 0:
            raise GitHubError((done.stderr or done.stdout).strip()[-300:])
        pages = json.loads(done.stdout)
        return [i for page in pages for i in page if "pull_request" not in i]

    def _via_http(self) -> List[Dict[str, Any]]:
        url = f"https://api.github.com/repos/{self.repo}/issues?state=open&per_page=100"
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "poker-arena-registry",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        if self._etag:
            headers["If-None-Match"] = self._etag
        try:
            with urllib.request.urlopen(
                urllib.request.Request(url, headers=headers), timeout=30
            ) as response:
                self._etag = response.headers.get("ETag")
                self._cache = [
                    i
                    for i in json.loads(response.read())
                    if "pull_request" not in i
                ]
        except urllib.error.HTTPError as exc:
            if exc.code == 304:
                return list(self._cache)
            raise GitHubError(f"GitHub answered HTTP {exc.code}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise GitHubError(f"cannot reach GitHub: {exc}") from exc
        return list(self._cache)

    def comment(self, number: int, body: str) -> bool:
        """Posts a comment; False if that is not possible (never raises)."""
        if not self._gh_ready():
            return False
        done = subprocess.run(
            [
                "gh",
                "issue",
                "comment",
                str(number),
                "-R",
                self.repo,
                "--body",
                body,
            ],
            capture_output=True,
            text=True,
            timeout=60,
            stdin=subprocess.DEVNULL,
        )
        return done.returncode == 0


# -- the thing the sync loop uses ---------------------------------------


def feedback_text(decision: Decision) -> str:
    reg = decision.registration
    if decision.status == "accepted":
        return (
            f"Registered as **{reg.team}**. Your repository {reg.repo} will "
            "be "
            "fetched within a minute and played from then on. Push to it to "
            "update your bot. The Submissions page on the results site shows "
            "whether each fetch worked."
        )
    if decision.status == "pending":
        return (
            f"Thanks. **{reg.team}** is registered and waiting for the "
            "organiser's approval (they add the `approved` label)."
        )
    return (
        f"This registration was **not accepted**: {decision.reason}.\n\n"
        "Edit this issue to fix it (it is checked again automatically) or "
        "open a new one."
    )


class Registry:
    """Turns registration issues into teams; used like a TeamsFile.

    ``current`` fetches the issues, decides each one, remembers the decisions
    in the store (the website shows the pending and rejected ones), comments on
    an issue when its outcome changes, and returns the accepted teams. If
    GitHub cannot be reached it keeps using the last good answer.
    """

    def __init__(
        self,
        client: Any,
        store: Store,
        *,
        open_registration: bool = False,
        max_per_user: int = 1,
        feedback: bool = True,
    ) -> None:
        self.client = client
        self.store = store
        self.open_registration = open_registration
        self.max_per_user = max_per_user
        self.feedback = feedback
        self._good: Optional[List[TeamSource]] = None
        self._last_error: Optional[str] = None
        self._warned_comments = False

    def current(
        self, report: Callable[[str], None] = print
    ) -> List[TeamSource]:
        try:
            issues = self.client.issues()
        except GitHubError as exc:
            if str(exc) != self._last_error:
                report(
                    f"[registry] cannot read the registry, keeping the "
                    f"previous list: {exc}"
                )
                self._last_error = str(exc)
            return list(self._good or [])
        self._last_error = None
        registrations = [r for r in map(parse_issue, issues) if r is not None]
        decisions = decide(
            registrations,
            self.store,
            open_registration=self.open_registration,
            max_per_user=self.max_per_user,
        )
        sources: List[TeamSource] = []
        for decision in decisions:
            self._record(decision, report)
            if decision.status == "accepted":
                sources.append(decision.source)
        self.store.drop_registrations_except(
            {d.registration.issue for d in decisions}
        )
        self._good = sources
        return list(sources)

    def _record(
        self, decision: Decision, report: Callable[[str], None]
    ) -> None:
        reg = decision.registration
        before = self.store.registrations().get(reg.issue)
        self.store.set_registration(
            reg.issue,
            {
                "team": reg.team,
                "user": reg.user,
                "repo": reg.repo,
                "status": decision.status,
                "message": decision.reason,
            },
        )
        if decision.status == "accepted":
            self.store.claim_team(reg.team, reg.user, reg.issue)
        key = f"{decision.status}|{decision.reason}|{reg.team}|{reg.repo}"
        if before is None or before.get("feedback") != key:
            report(
                f"[registry] #{reg.issue} {reg.team} ({reg.user}): "
                f"{decision.status}"
                + (f" - {decision.reason}" if decision.reason else "")
            )
            if self.feedback and self.client.comment(
                reg.issue, feedback_text(decision)
            ):
                self.store.set_registration_feedback(reg.issue, key)
            elif self.feedback and not self._warned_comments:
                report(
                    "[registry] cannot comment on issues here (is the "
                    "'gh' command signed in?); registrants will not get "
                    "replies"
                )
                self._warned_comments = True
