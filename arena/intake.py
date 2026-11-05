"""Submissions: copy, version by content hash, validate, activate.

A submission is a bot directory containing ``bot.py`` (or a single
``.py`` file), given as a local path or a git URL. Its version id is a
hash of its contents, so resubmitting identical code is a no-op and every
result can name exactly which code produced it.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from .store import Store
from .validate import smoke_test

TEAM_NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")
BRANCH = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,99}$")
MAX_FILES = 2000
MAX_BYTES = 25 * 1024 * 1024
IGNORED = ("__pycache__", ".git", ".venv", "venv", ".DS_Store")


class SubmissionError(Exception):
    """The submission cannot even be turned into a bot directory."""


@dataclass
class SubmitResult:
    team: str
    digest: str
    status: str  # "valid" | "invalid" | "unchanged"
    message: str

    @property
    def accepted(self) -> bool:
        return self.status in ("valid", "unchanged")


def is_git_url(source: str) -> bool:
    return source.startswith(
        ("http://", "https://", "git@", "ssh://", "file://")
    ) or (source.endswith(".git") and not Path(source).exists())


def _git_environment() -> dict:
    """An environment in which git can never wait for a person.

    A private repository would otherwise ask for a password. On Windows that
    is a pop-up window from Git Credential Manager, and a loop that clones
    twenty repositories would sit waiting on it. With these set, git fails
    straight away with an authentication error instead.
    """
    environment = dict(os.environ)
    environment.update(
        GIT_TERMINAL_PROMPT="0",
        GCM_INTERACTIVE="never",
        GIT_ASKPASS="echo",
        SSH_ASKPASS="echo",
    )
    return environment


def _bot_files(root: Path) -> List[Path]:
    files = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        if any(part in IGNORED for part in relative.parts):
            continue
        if path.suffix == ".pyc":
            continue
        files.append(path)
    return files


def content_hash(root: Path) -> str:
    """Stable hash of a bot directory's relevant files."""
    digest = hashlib.sha256()
    total = 0
    files = _bot_files(root)
    if len(files) > MAX_FILES:
        raise SubmissionError(f"too many files ({len(files)} > {MAX_FILES})")
    for path in files:
        data = path.read_bytes()
        total += len(data)
        if total > MAX_BYTES:
            raise SubmissionError(
                f"submission larger than {MAX_BYTES // (1024 * 1024)} MB"
            )
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(b"\0")
        digest.update(data)
        digest.update(b"\0")
    return digest.hexdigest()[:12]


def _materialise(
    source: str,
    workdir: Path,
    branch: Optional[str] = None,
    clone_timeout: float = 90.0,
) -> Path:
    """Returns a directory with ``bot.py`` for the given source."""
    if source.startswith("-"):
        # Would be read by git as an option, not as a repository.
        raise SubmissionError("a source cannot start with '-'")
    if branch is not None and not BRANCH.match(branch):
        raise SubmissionError(f"not a usable branch name: {branch!r}")
    if is_git_url(source):
        target = workdir / "clone"
        command = ["git", "-c", "protocol.ext.allow=never", "clone"]
        command += ["--depth", "1", "--no-tags", "--single-branch"]
        if branch:
            command += ["--branch", branch]
        command += [
            "--",
            source,
            str(target),
        ]  # "--": source is never an option
        try:
            subprocess.run(
                command,
                check=True,
                capture_output=True,
                text=True,
                stdin=subprocess.DEVNULL,
                env=_git_environment(),
                timeout=clone_timeout,
            )
        except subprocess.CalledProcessError as exc:
            raise SubmissionError(
                f"git clone failed: {exc.stderr[-300:]}"
            ) from exc
        except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
            raise SubmissionError(f"git clone failed: {exc}") from exc
        path = target
    else:
        path = Path(source)
        if not path.exists():
            raise SubmissionError(f"not found: {source}")

    if path.is_file():
        folder = workdir / "single"
        folder.mkdir()
        shutil.copy2(path, folder / "bot.py")
        return folder
    if not (path / "bot.py").is_file():
        raise SubmissionError("the bot directory must contain bot.py")
    return path


def submit(
    store: Store,
    team: str,
    source: str,
    *,
    validate: bool = True,
    move_timeout: float = 1.0,
    branch: Optional[str] = None,
    clone_timeout: float = 90.0,
) -> SubmitResult:
    """Adds a version of ``team``'s bot; activates it when it validates.

    A failing submission is recorded but never replaces the team's
    current version, so a broken last-minute push cannot take a team
    out of the ladder.
    """
    if not TEAM_NAME.match(team):
        raise SubmissionError(
            "team names are 1-32 characters of a-z, 0-9, '-' and '_'"
        )

    with tempfile.TemporaryDirectory() as tmp:
        folder = _materialise(
            source, Path(tmp), branch=branch, clone_timeout=clone_timeout
        )
        digest = content_hash(folder)
        existing = store.get_version(digest)
        if existing and existing.team == team:
            if existing.status == "valid":
                store.set_current(team, digest)
                return SubmitResult(
                    team, digest, "unchanged", "identical code, no change"
                )
            return SubmitResult(
                team, digest, "invalid", existing.message or "invalid"
            )
        if existing and existing.team != team:
            raise SubmissionError(
                f"identical code was already submitted by '{existing.team}'"
            )

        destination = store.root / "versions" / team / digest
        if destination.exists():
            shutil.rmtree(destination)
        shutil.copytree(
            folder,
            destination,
            ignore=shutil.ignore_patterns(*IGNORED, "*.pyc"),
        )

    if validate:
        report = smoke_test(
            destination,
            log_dir=store.root / "logs" / team / digest,
            move_timeout=move_timeout,
        )
        ok, message = report.ok, report.message
    else:
        ok, message = True, "validation skipped"

    status = "valid" if ok else "invalid"
    store.add_version(team, digest, str(destination), status, message)
    if ok:
        store.set_current(team, digest)
    return SubmitResult(team, digest, status, message)


def scan_directory(
    store: Store, directory: Path, **kwargs
) -> List[SubmitResult]:
    """Submits every ``<directory>/<team>/`` whose code has changed."""
    results: List[SubmitResult] = []
    if not directory.is_dir():
        return results
    for entry in sorted(directory.iterdir()):
        if not entry.is_dir() or entry.name.startswith("."):
            continue
        if not (entry / "bot.py").is_file():
            continue
        team = entry.name.lower()
        try:
            digest = content_hash(entry)
        except SubmissionError as exc:
            results.append(SubmitResult(team, "", "invalid", str(exc)))
            continue
        known = store.get_version(digest)
        if known is not None:
            # Already seen. If the directory was reverted to an older
            # valid version, make that version current again.
            if (
                known.status == "valid"
                and known.team == team
                and store.current_hash(team) != digest
            ):
                store.set_current(team, digest)
                results.append(
                    SubmitResult(team, digest, "valid", "reverted to earlier")
                )
            continue
        try:
            results.append(submit(store, team, str(entry), **kwargs))
        except SubmissionError as exc:
            results.append(SubmitResult(team, digest, "invalid", str(exc)))
    return results
