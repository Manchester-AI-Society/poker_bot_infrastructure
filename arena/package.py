"""Submission files: teams pack a bot into one pickle, the organiser imports.

A team runs ``python -m arena pack bots/myteam --team NAME``: the bot is
loaded, checked (loads again from the pickle, plays legally, on time) and
written to ``NAME.pkl``, which the team uploads through the organiser's form.
The organiser runs ``python -m arena import FOLDER`` over everything the form
collected.

See ``arena/pickling.py`` for the file format. The importer treats every file
as untrusted: it reads the label without executing anything, checks the
checksum and the Python version, and only the child process that plays the
bot ever unpickles the bot itself.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from .intake import IGNORED, TEAM_NAME, SubmissionError, submit
from .pickling import (
    BOT_FILE,
    REQUIRED_PYTHON,
    PickleError,
    digest_of,
    pickle_bot,
    python_label,
    read_submission,
    write_submission,
)
from .store import Store
from .validate import smoke_test


class PackError(Exception):
    """The bot cannot be packed (wrong layout, too big, fails its check)."""


# -- packing (a team's side) ---


@dataclass
class PackResult:
    path: Path
    team: str
    digest: str
    bytes: int


def pack(
    bot: Path,
    team: str,
    out_dir: Path,
    *,
    validate: bool = True,
    log=lambda message: None,
) -> PackResult:
    """Checks a bot and writes ``<team>.pkl`` into ``out_dir``."""
    if not TEAM_NAME.match(team):
        raise PackError(
            "a team name is lowercase letters, digits, '-' and '_', up to 32 "
            "characters, starting with a letter or digit"
        )
    if sys.version_info[:2] != REQUIRED_PYTHON:
        raise PackError(
            f"pack with Python {python_label(REQUIRED_PYTHON)} (this is "
            f"{python_label()}): a pickle holds bytecode, which differs "
            "between Python versions"
        )
    bot = Path(bot)
    if not bot.exists():
        raise PackError(f"not found: {bot}")
    with tempfile.TemporaryDirectory() as tmp:
        if bot.is_file():
            folder = Path(tmp) / "single"
            folder.mkdir()
            shutil.copy2(bot, folder / "bot.py")
        else:
            folder = bot
        if not (folder / "bot.py").is_file():
            raise PackError(
                "the bot folder must contain bot.py at its top level"
            )
        try:
            payload = pickle_bot(folder)
        except PickleError as exc:
            raise PackError(str(exc)) from exc
        target = out_dir / f"{team}.pkl"
        write_submission(target, team, payload)
        if validate:
            # Check exactly what the organiser will run: the bot loaded from
            # the pickle in a fresh process, nothing else from your folder.
            log("checking that your bot loads and plays legally...")
            try:
                document = read_submission(target)
            except PickleError as exc:
                target.unlink(missing_ok=True)
                raise PackError(str(exc)) from exc
            check = Path(tmp) / "check"
            check.mkdir()
            (check / BOT_FILE).write_bytes(document["bot"])
            report = smoke_test(check, log_dir=Path(tmp) / "logs")
            if not report.ok:
                target.unlink(missing_ok=True)
                raise PackError(
                    f"your bot fails its check: {report.message}\n"
                    "Fix that first (python -m arena validate shows the same "
                    "check), then pack again."
                )
    return PackResult(target, team, digest_of(payload), target.stat().st_size)


# -- unpacking (the organiser's side; the file is untrusted) ---


def unpack(path: Path, destination: Path) -> Dict[str, object]:
    """Checks a submission file and writes its bot to ``destination``.

    Returns the file's label. Raises SubmissionError for anything wrong.
    """
    try:
        document = read_submission(path)
    except PickleError as exc:
        raise SubmissionError(str(exc)) from exc
    if not TEAM_NAME.match(document["team"]):
        raise SubmissionError("the file names no valid team")
    destination.mkdir(parents=True, exist_ok=True)
    (destination / BOT_FILE).write_bytes(document["bot"])
    return {
        "team": document["team"],
        "created": document.get("created"),
        "digest": document["digest"],
    }


# -- importing everything the form collected ---------------------


@dataclass
class ImportResult:
    file: str
    team: Optional[str]
    status: (
        str  # "valid" | "unchanged" | "invalid" | "rejected" | "superseded"
    )
    message: str

    @property
    def ok(self) -> bool:
        return self.status in ("valid", "unchanged", "superseded")


def find_submissions(folder: Path) -> List[Path]:
    return sorted(
        p
        for p in Path(folder).rglob("*.pkl")
        if p.is_file() and not any(part in IGNORED for part in p.parts)
    )


def import_submissions(
    store: Store,
    folder: Path,
    *,
    validate: bool = True,
    move_timeout: float = 1.0,
) -> List[ImportResult]:
    """Imports every submission file under ``folder``.

    A team that submitted more than once gets its newest file (by the time in
    the file's own label) played; a newer file that fails never replaces an
    older one that works.
    """
    candidates = []
    results: List[ImportResult] = []
    for path in find_submissions(folder):
        kept = Path(tempfile.mkdtemp(prefix="arena-import-"))
        try:
            manifest = unpack(path, kept / "bot")
        except SubmissionError as exc:
            shutil.rmtree(kept, ignore_errors=True)
            results.append(ImportResult(path.name, None, "rejected", str(exc)))
            continue
        candidates.append(
            (float(manifest.get("created") or 0), path, manifest, kept)
        )

    candidates.sort(key=lambda item: (item[0], item[1].name))
    try:
        for _, path, manifest, kept in candidates:
            team = manifest["team"]
            try:
                outcome = submit(
                    store,
                    team,
                    str(kept / "bot"),
                    validate=validate,
                    move_timeout=move_timeout,
                )
            except SubmissionError as exc:
                results.append(
                    ImportResult(path.name, team, "rejected", str(exc))
                )
                continue
            results.append(
                ImportResult(path.name, team, outcome.status, outcome.message)
            )
    finally:
        for _, _, _, kept in candidates:
            shutil.rmtree(kept, ignore_errors=True)

    # Several files from one team: only the newest working one is played.
    newest_ok: Dict[str, int] = {}
    for index, result in enumerate(results):
        if result.team and result.status in ("valid", "unchanged"):
            newest_ok[result.team] = index
    for index, result in enumerate(results):
        if (
            result.team
            and result.status in ("valid", "unchanged")
            and newest_ok[result.team] != index
        ):
            result.status = "superseded"
            result.message = "replaced by this team's newer submission"
    return results
