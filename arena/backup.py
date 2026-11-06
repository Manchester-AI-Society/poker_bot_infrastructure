"""The backup path: bots handed in as zip files also play in the live event.

A team that cannot connect over websockets (a blocked network, a flaky laptop)
uploads a zip through the backup form. The organiser imports it
(``arena import``) and then ``arena backup-run`` plays that bot on the
organiser's machine: it makes the team a player on the poker server and starts
the bot as an ordinary websocket client, so it sits in the lobby and is seated
like everyone else's.

By default only teams that are NOT already connected live are run
("websockets first, the form as the backup"). The bots are the teams' code,
run unsandboxed on this machine, like everything else imported from a zip.
"""

from __future__ import annotations

import os
import secrets
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from .store import Store

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MAX_RESTARTS = 3


class BackupError(Exception):
    """The backup bots could not be set up."""


class TeamExists(BackupError):
    """That name is already a player on the server."""


# -- the server, as the runner needs it -----------------------------------


class AdminServer:
    """The poker server's admin API (a thin wrapper, easy to fake in tests)."""

    def __init__(self, base_url: str, admin_key: str) -> None:
        from admin_sdk import AdminSDKClient, AdminSDKConfiguration

        self._client = AdminSDKClient(
            AdminSDKConfiguration(base_url=base_url, admin_api_key=admin_key)
        )

    def lobby(self) -> List[str]:
        return list(self._client.get_lobby().get("players", []))

    def tournament_status(self) -> str:
        return str(self._client.get_tournament().get("status", ""))

    def create_player(self, name: str, key: str) -> None:
        try:
            result = self._client.create_player(name, api_key=key)
        except Exception as exc:  # AdminSDKRequestError and friends
            if "409" in str(exc) or "exist" in str(exc).lower():
                raise TeamExists(name) from exc
            raise BackupError(f"cannot create {name}: {exc}") from exc
        # For a name that already exists the server answers 200 with
        # {"created": false} and records NO key: that is a refusal, not
        # a success (the bot would be told its key is invalid).
        if isinstance(result, dict) and result.get("created") is False:
            raise TeamExists(name)

    def rotate_key(self, name: str, key: str) -> None:
        try:
            self._client.rotate_player_key(name, api_key=key)
        except Exception as exc:
            raise BackupError(f"cannot take over {name}: {exc}") from exc


# -- starting a bot -------------------------------------------------------


def spawn_bot(
    team: str, path: Path, server_url: str, key: str, log_path: Path
):
    """Starts a team's bot as a websocket client; returns the process."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        [str(REPO_ROOT)]
        + ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else [])
    )
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    log = open(log_path, "ab")
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "player_sdk",
            "bot.py",
            "--tournament",
            "--server-url",
            server_url,
            "--api-key",
            key,
        ],
        cwd=str(path),  # the bot's own folder, so its helper files import
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=log,
        stderr=subprocess.STDOUT,
    )
    process._arena_log = log  # closed with the process
    return process


@dataclass
class Running:
    team: str
    path: Path
    key: str
    process: Any
    restarts: int = 0
    state: str = "running"  # running | finished | failed


@dataclass
class Plan:
    run: List[Tuple[str, Path]] = field(default_factory=list)
    skipped: List[Tuple[str, str]] = field(default_factory=list)


def plan(
    store: Store,
    connected: Sequence[str],
    *,
    only_missing: bool = True,
    teams: Optional[Sequence[str]] = None,
) -> Plan:
    """Which imported teams should be run for them."""
    result = Plan()
    wanted = set(teams) if teams else None
    live = set(connected)
    by_team = {v.team: v for v in store.current_versions()}
    for name in sorted(wanted or by_team):
        version = by_team.get(name)
        if version is None:
            result.skipped.append((name, "no imported bot"))
        elif only_missing and name in live:
            result.skipped.append((name, "already connected live"))
        else:
            result.run.append((name, Path(version.path)))
    return result


class BackupRunner:
    """Runs the backup bots and keeps them running."""

    def __init__(
        self,
        store: Store,
        server: Any,
        server_url: str,
        *,
        spawn: Callable[..., Any] = spawn_bot,
        log: Callable[[str], None] = print,
        max_restarts: int = DEFAULT_MAX_RESTARTS,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.store = store
        self.server = server
        self.server_url = server_url
        self._spawn = spawn
        self._log = log
        self._max_restarts = max_restarts
        self._sleep = sleep
        self.running: Dict[str, Running] = {}
        # A server that still shows the PREVIOUS event as finished must not
        # end this one before it has even begun.
        self._initial_status: Optional[str] = None
        self._seen_running = False

    def _log_path(self, team: str) -> Path:
        return self.store.root / "logs" / team / "backup.log"

    def start(
        self, run: Sequence[Tuple[str, Path]], *, take_over: bool = False
    ) -> List[Tuple[str, str]]:
        """Makes each team a player and starts its bot; returns problems."""
        problems: List[Tuple[str, str]] = []
        self._initial_status = self._status()
        for team, path in run:
            key = "bk-" + secrets.token_hex(16)
            try:
                try:
                    self.server.create_player(team, key)
                except TeamExists:
                    if not take_over:
                        problems.append(
                            (
                                team,
                                "the name is already a player on the "
                                "server (a live team?); use --take-over to "
                                "replace its key",
                            )
                        )
                        continue
                    self.server.rotate_key(team, key)
            except BackupError as exc:
                problems.append((team, str(exc)))
                continue
            process = self._spawn(
                team, path, self.server_url, key, self._log_path(team)
            )
            self.running[team] = Running(team, path, key, process)
            self._log(
                f"[backup] {team}: started (log: {self._log_path(team)})"
            )
        return problems

    def _status(self) -> str:
        try:
            return self.server.tournament_status()
        except Exception:
            return ""

    def _over(self, status: str) -> bool:
        """True when THIS event has finished (not an earlier one)."""
        if status == "running":
            self._seen_running = True
        return status == "finished" and (
            self._seen_running or self._initial_status != "finished"
        )

    def poll_once(self) -> str:
        """One supervision pass; returns "finished" once the event is over."""
        status = self._status()
        over = self._over(status)
        for entry in self.running.values():
            if entry.state != "running":
                continue
            code = entry.process.poll()
            if code is None:
                continue
            if code == 0 or over:
                entry.state = "finished"
                self._log(f"[backup] {entry.team}: finished")
            elif entry.restarts < self._max_restarts:
                entry.restarts += 1
                self._log(
                    f"[backup] {entry.team}: exited with {code}; restarting "
                    f"({entry.restarts}/{self._max_restarts})"
                )
                entry.process = self._spawn(
                    entry.team,
                    entry.path,
                    self.server_url,
                    entry.key,
                    self._log_path(entry.team),
                )
            else:
                entry.state = "failed"
                self._log(
                    f"[backup] {entry.team}: gave up after "
                    f"{self._max_restarts} restarts; see "
                    f"{self._log_path(entry.team)}"
                )
        if over:
            return "finished"
        # An earlier event's result still on the server is not ours.
        return "waiting" if status == "finished" else status

    def supervise(
        self,
        *,
        poll_seconds: float = 2.0,
        stop: Callable[[], bool] = lambda: False,
    ) -> None:
        """Keeps the bots running until the tournament ends (or ``stop``)."""
        while not stop():
            status = self.poll_once()
            if status == "finished":
                return
            if self.running and all(
                e.state != "running" for e in self.running.values()
            ):
                return
            self._sleep(poll_seconds)

    def stop_all(self) -> None:
        for entry in self.running.values():
            process = entry.process
            try:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except Exception:
                        process.kill()
            except Exception:
                pass
            log = getattr(process, "_arena_log", None)
            if log is not None:
                try:
                    log.close()
                except OSError:
                    pass
