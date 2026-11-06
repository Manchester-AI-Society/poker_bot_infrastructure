"""Submission files: teams pack a bot into one zip, the organiser imports them.

A team runs ``python -m arena pack bots/myteam --team NAME``: the bot is
checked (loads, plays legally, on time) and written to ``NAME.zip``, which
the team uploads through the organiser's form. The organiser runs
``python -m arena import FOLDER`` over everything the form collected.

The zip carries a small manifest (team name, a hash of the files, when it was
made). The importer treats every zip as untrusted input: paths are checked
before anything is written, links and oversized or bomb-like archives are
refused, and the files must match the hash in the manifest.
"""

from __future__ import annotations

import json
import shutil
import tempfile
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Dict, List, Optional

from .intake import (
    IGNORED,
    MAX_BYTES,
    MAX_FILES,
    TEAM_NAME,
    SubmissionError,
    _bot_files,
    content_hash,
    submit,
)
from .store import Store
from .validate import smoke_test

MANIFEST = "arena-submission.json"
FORMAT = 1
# A zip claiming to expand to more than this many times its own size is a bomb.
MAX_RATIO = 200
CHUNK = 1024 * 256


class PackError(Exception):
    """The bot cannot be packed (wrong layout, too big, fails its check)."""


# -- packing (a team's side) ---


@dataclass
class PackResult:
    path: Path
    team: str
    digest: str
    files: int
    bytes: int


def pack(
    bot: Path,
    team: str,
    out_dir: Path,
    *,
    validate: bool = True,
    log=lambda message: None,
) -> PackResult:
    """Checks a bot and writes ``<team>.zip`` into ``out_dir``."""
    if not TEAM_NAME.match(team):
        raise PackError(
            "a team name is lowercase letters, digits, '-' and '_', up to 32 "
            "characters, starting with a letter or digit"
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
            digest = content_hash(folder)
        except SubmissionError as exc:
            raise PackError(str(exc)) from exc
        files = _bot_files(folder)
        for path in files:
            if path.is_symlink():
                raise PackError(
                    f"{path.relative_to(folder)} is a link; links are not "
                    "allowed in a submission"
                )
        if validate:
            log("checking that your bot loads and plays legally...")
            report = smoke_test(folder, log_dir=Path(tmp) / "logs")
            if not report.ok:
                raise PackError(
                    f"your bot fails its check: {report.message}\n"
                    "Fix that first (python -m arena validate shows the same "
                    "check), then pack again."
                )
        out_dir.mkdir(parents=True, exist_ok=True)
        target = out_dir / f"{team}.zip"
        total = 0
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(
                MANIFEST,
                json.dumps(
                    {
                        "format": FORMAT,
                        "team": team,
                        "digest": digest,
                        "created": time.time(),
                    },
                    indent=2,
                ),
            )
            for path in files:
                relative = path.relative_to(folder).as_posix()
                archive.write(path, relative)
                total += path.stat().st_size
    return PackResult(target, team, digest, len(files), total)


# -- unpacking (the organiser's side; the zip is untrusted) ---


def _clean_name(name: str) -> Optional[PurePosixPath]:
    """A safe relative path for a zip entry, or None if it is not safe."""
    name = name.replace("\\", "/")
    if not name or name.startswith("/") or ":" in name.split("/")[0]:
        return None
    path = PurePosixPath(name)
    if path.is_absolute() or any(part in ("..", "") for part in path.parts):
        return None
    return path


def unpack(archive_path: Path, destination: Path) -> Dict[str, object]:
    """Extracts a submission zip into ``destination``; returns its manifest.

    Raises SubmissionError for anything unsafe or malformed.
    """
    try:
        archive = zipfile.ZipFile(archive_path)
    except (zipfile.BadZipFile, OSError) as exc:
        raise SubmissionError(f"not a readable zip file: {exc}") from exc
    with archive:
        infos = [i for i in archive.infolist() if not i.is_dir()]
        if len(infos) > MAX_FILES:
            raise SubmissionError(f"too many files ({len(infos)})")
        declared = sum(i.file_size for i in infos)
        if declared > MAX_BYTES:
            raise SubmissionError(
                f"expands to more than {MAX_BYTES // (1024 * 1024)} MB"
            )
        seen = set()
        for info in infos:
            clean = _clean_name(info.filename)
            if clean is None:
                raise SubmissionError(
                    f"unsafe path in the zip: {info.filename!r}"
                )
            if (info.external_attr >> 16) & 0o170000 == 0o120000:
                raise SubmissionError(f"{info.filename} is a link")
            if clean in seen:
                raise SubmissionError(f"{clean} appears twice in the zip")
            seen.add(clean)
            if (
                info.file_size > 1024 * 1024
                and info.file_size > MAX_RATIO * max(info.compress_size, 1)
            ):
                raise SubmissionError(
                    f"{clean} expands suspiciously (a zip bomb?)"
                )

        written = 0
        manifest_bytes = None
        for info in infos:
            clean = _clean_name(info.filename)
            target = destination / Path(*clean.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as source, open(target, "wb") as sink:
                while True:
                    chunk = source.read(CHUNK)
                    if not chunk:
                        break
                    written += len(chunk)
                    if written > MAX_BYTES:  # trust bytes read, not the header
                        raise SubmissionError(
                            "expands to more than "
                            f"{MAX_BYTES // (1024 * 1024)} MB"
                        )
                    sink.write(chunk)
            if clean.as_posix() == MANIFEST:
                manifest_bytes = target.read_bytes()
                target.unlink()
    if manifest_bytes is None:
        raise SubmissionError(
            f"no {MANIFEST}: make this zip with 'python -m arena pack'"
        )
    try:
        manifest = json.loads(manifest_bytes)
    except ValueError as exc:
        raise SubmissionError(f"{MANIFEST} is not valid JSON") from exc
    if not isinstance(manifest, dict) or manifest.get("format") != FORMAT:
        raise SubmissionError(
            "this zip was made by a different version of 'arena pack'"
        )
    team = manifest.get("team")
    if not isinstance(team, str) or not TEAM_NAME.match(team):
        raise SubmissionError("the zip names no valid team")
    if not (destination / "bot.py").is_file():
        raise SubmissionError("the zip has no bot.py at its top level")
    if content_hash(destination) != manifest.get("digest"):
        raise SubmissionError(
            "the files do not match the zip's own checksum (damaged or "
            "edited after packing)"
        )
    return manifest


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


def find_zips(folder: Path) -> List[Path]:
    return sorted(
        p
        for p in Path(folder).rglob("*.zip")
        if p.is_file() and not any(part in IGNORED for part in p.parts)
    )


def import_submissions(
    store: Store,
    folder: Path,
    *,
    validate: bool = True,
    move_timeout: float = 1.0,
) -> List[ImportResult]:
    """Imports every submission zip under ``folder``.

    A team that submitted more than once gets its newest zip (by the time in
    the zip's own manifest) played; a newer zip that fails never replaces an
    older one that works.
    """
    candidates = []
    results: List[ImportResult] = []
    for path in find_zips(folder):
        with tempfile.TemporaryDirectory() as tmp:
            staging = Path(tmp) / "bot"
            staging.mkdir()
            try:
                manifest = unpack(path, staging)
            except SubmissionError as exc:
                results.append(
                    ImportResult(path.name, None, "rejected", str(exc))
                )
                continue
            kept = Path(tempfile.mkdtemp(prefix="arena-import-"))
            shutil.copytree(staging, kept / "bot")
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

    # Several zips from one team: only the newest working one is played.
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
