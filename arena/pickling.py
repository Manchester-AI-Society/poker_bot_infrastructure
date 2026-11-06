"""The submission file: a team's bot as one pickle.

``python -m arena pack`` loads the team's bot, pickles the instance with
cloudpickle (the bot's own modules are pickled by value, so the file needs no
source), and writes ``TEAM.pkl``. The file is an ordinary pickle of a plain
dict, so the organiser can read its label (team, Python version, digest)
WITHOUT running anything: the reader below refuses every global. The bot
itself is the ``bot`` bytes inside, and is only ever unpickled in a child
process (``arena.bothost``), never in the organiser's own process.

Unpickling runs the team's code, exactly as importing their bot.py did before.
The bots are not sandboxed.

A pickle holds Python bytecode, so a bot must be packed with the same Python
minor version as the machine that plays it (``REQUIRED_PYTHON``).
"""

from __future__ import annotations

import hashlib
import io
import os
import pickle
import sys
import time
from pathlib import Path
from typing import Any, Dict, Tuple

import cloudpickle

from player_sdk.bot_interface import PokerBot
from player_sdk.loader import load_bot_from_file

FORMAT = 1
# The Python minor version teams must pack with (the organiser's machine).
REQUIRED_PYTHON: Tuple[int, int] = (3, 14)
MAX_BYTES = 25 * 1024 * 1024
BOT_FILE = "bot.pkl"  # the inner pickle inside an imported version folder


class PickleError(Exception):
    """A submission file cannot be made or is not acceptable."""


class _Plain(pickle.Unpickler):
    """Reads plain data only: any global (a class or function) is refused."""

    def find_class(self, module: str, name: str):
        raise pickle.UnpicklingError(
            f"a submission may not contain {module}.{name}"
        )


def digest_of(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()[:12]


def python_label(version: Tuple[int, int] | None = None) -> str:
    major, minor = version or sys.version_info[:2]
    return f"{major}.{minor}"


# -- a team's side ---------------------------------------------------


def _inside(folder: Path, path: Path) -> bool:
    try:
        path.resolve().relative_to(folder)
        return True
    except (ValueError, OSError):
        return False


def pickle_bot(folder: Path) -> bytes:
    """Loads the bot in ``folder`` and returns its cloudpickle bytes."""
    folder = Path(folder).resolve()
    bot_file = folder / "bot.py"
    if not bot_file.is_file():
        raise PickleError("the bot folder must contain bot.py")
    before = dict(sys.modules)
    added = str(folder)
    sys.path.append(added)
    previous = os.getcwd()
    registered = []
    try:
        os.chdir(folder)
        try:
            bot = load_bot_from_file(bot_file)
        except Exception as exc:
            raise PickleError(f"your bot does not load: {exc}") from exc
        # Everything the team wrote (bot.py and any helper modules next to
        # it) travels inside the pickle; libraries stay references.
        for module in list(sys.modules.values()):
            path = getattr(module, "__file__", None)
            if path and _inside(folder, Path(path)):
                cloudpickle.register_pickle_by_value(module)
                registered.append(module)
        try:
            return cloudpickle.dumps(bot)
        except Exception as exc:
            raise PickleError(
                "your bot holds something that cannot be pickled "
                f"({type(exc).__name__}: {exc}). Open files, sockets and "
                "locks cannot travel; load models and data in __init__ "
                "into plain attributes."
            ) from exc
    finally:
        for module in registered:
            try:
                cloudpickle.unregister_pickle_by_value(module)
            except Exception:
                pass
        os.chdir(previous)
        if added in sys.path:
            sys.path.remove(added)
        # Leave no trace of the team's modules (a later bot named bot.py
        # must not find this one).
        for name, module in list(sys.modules.items()):
            path = getattr(module, "__file__", None)
            if path and _inside(folder, Path(path)):
                del sys.modules[name]
        for name, module in before.items():
            sys.modules.setdefault(name, module)


def write_submission(path: Path, team: str, payload: bytes) -> None:
    """Writes the submission file for ``team``."""
    document: Dict[str, Any] = {
        "format": FORMAT,
        "team": team,
        "created": time.time(),
        "python": [sys.version_info[0], sys.version_info[1]],
        "digest": digest_of(payload),
        "bot": payload,
    }
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(pickle.dumps(document, protocol=4))


# -- the organiser's side (the file is untrusted) --------------------


def read_submission(path: Path) -> Dict[str, Any]:
    """Reads and checks a submission file WITHOUT executing anything in it.

    Returns the document (team, created, python, digest, bot bytes).
    """
    path = Path(path)
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise PickleError(f"not readable: {exc}") from exc
    if size > MAX_BYTES:
        raise PickleError(
            f"larger than {MAX_BYTES // (1024 * 1024)} MB ({size} bytes)"
        )
    try:
        document = _Plain(io.BytesIO(path.read_bytes())).load()
    except Exception as exc:
        raise PickleError(
            f"not a submission made by 'arena pack' ({type(exc).__name__}: "
            f"{exc})"
        ) from exc
    if not isinstance(document, dict) or document.get("format") != FORMAT:
        raise PickleError(
            "this file was made by a different version of 'arena pack'"
        )
    payload = document.get("bot")
    team = document.get("team")
    if not isinstance(payload, (bytes, bytearray)) or not payload:
        raise PickleError("the file holds no bot")
    if not isinstance(team, str):
        raise PickleError("the file names no team")
    version = document.get("python")
    if (
        not isinstance(version, list)
        or len(version) != 2
        or not all(isinstance(n, int) for n in version)
    ):
        raise PickleError("the file does not say which Python made it")
    if digest_of(bytes(payload)) != document.get("digest"):
        raise PickleError(
            "the bot does not match the file's own checksum (damaged or "
            "edited after packing)"
        )
    if tuple(version) != sys.version_info[:2]:
        raise PickleError(
            f"packed with Python {version[0]}.{version[1]}, but this machine "
            f"runs {python_label()}: ask the team to pack again with "
            f"Python {python_label()}"
        )
    document["bot"] = bytes(payload)
    return document


# -- running a pickled bot (called only inside a child process) ------


def load_pickled_bot(path: Path) -> PokerBot:
    """Unpickles the bot bytes in ``path`` (a bot.pkl); runs team code."""
    bot = cloudpickle.loads(Path(path).read_bytes())
    if not isinstance(bot, PokerBot):
        raise PickleError(
            f"the pickle holds a {type(bot).__name__}, not a PokerBot"
        )
    return bot
