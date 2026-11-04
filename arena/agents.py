"""Agents: something that turns a state message into an action reply.

``ProcessAgent`` runs a participant bot in a child process (the
competition path). ``LocalAgent`` runs a bot in-process, which is used
for built-in baselines and tests where isolation is not needed.
"""

from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any, Callable, Dict, Mapping, Optional

from player_sdk.bot_interface import PokerBot
from player_sdk.parser import GameStateParser

from .bothost import act_on_message

REPO_ROOT = Path(__file__).resolve().parents[1]


class AgentFault(Exception):
    """The bot failed to produce a usable reply for this request."""


class AgentTimeout(AgentFault):
    """The bot did not reply within the move time limit."""


class AgentCrashed(AgentFault):
    """The bot process exited or its stdout closed."""


class Agent:
    """Interface: ``request`` returns a reply or raises AgentFault."""

    def request(self, message: Mapping[str, Any], timeout: float):
        raise NotImplementedError

    def close(self) -> None:  # pragma: no cover - trivial
        pass


class LocalAgent(Agent):
    """Runs a PokerBot in this process (no isolation, no timeout)."""

    def __init__(self, bot_factory: Callable[[], PokerBot]):
        self._bot = bot_factory()
        self._parser = GameStateParser()

    def request(self, message: Mapping[str, Any], timeout: float):
        try:
            return act_on_message(self._bot, self._parser, message)
        except Exception as exc:
            raise AgentFault(f"{type(exc).__name__}: {exc}") from exc


class ProcessAgent(Agent):
    """Runs a participant bot in its own child process."""

    def __init__(
        self,
        target: Path,
        *,
        log_path: Optional[Path] = None,
        startup_timeout: float = 20.0,
    ):
        self._target = Path(target)
        self._log_file = None
        self._lines: "queue.Queue[Optional[str]]" = queue.Queue()
        if log_path is not None:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            self._log_file = open(log_path, "ab")
        env = dict(os.environ)
        env["PYTHONPATH"] = os.pathsep.join(
            [str(REPO_ROOT)]
            + ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else [])
        )
        env["PYTHONUNBUFFERED"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        self._proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "arena.bothost",
                str(self._target),
            ],
            cwd=REPO_ROOT,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=self._log_file or subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            bufsize=1,
        )
        threading.Thread(target=self._pump, daemon=True).start()
        self._await_ready(startup_timeout)

    def _pump(self) -> None:
        try:
            for line in self._proc.stdout:
                self._lines.put(line)
        except (OSError, ValueError):
            pass
        finally:
            self._lines.put(None)

    def _read_reply(self, timeout: float) -> Dict[str, Any]:
        try:
            line = self._lines.get(timeout=timeout)
        except queue.Empty:
            self.close()
            raise AgentTimeout(f"no reply within {timeout:.2f}s") from None
        if line is None:
            self.close()
            raise AgentCrashed("bot process exited")
        try:
            reply = json.loads(line)
        except ValueError:
            self.close()
            raise AgentFault("reply was not valid JSON") from None
        if not isinstance(reply, dict):
            self.close()
            raise AgentFault("reply was not a JSON object")
        return reply

    def _await_ready(self, timeout: float) -> None:
        try:
            reply = self._read_reply(timeout)
        except AgentFault as exc:
            raise AgentCrashed(f"bot failed to start: {exc}") from exc
        if reply.get("type") != "ready":
            self.close()
            message = str(reply.get("message", reply))
            raise AgentCrashed(f"bot failed to load: {message[-600:]}")

    def request(self, message: Mapping[str, Any], timeout: float):
        if self._proc.poll() is not None:
            raise AgentCrashed("bot process is not running")
        try:
            self._proc.stdin.write(json.dumps(message) + "\n")
            self._proc.stdin.flush()
        except (BrokenPipeError, OSError, ValueError):
            self.close()
            raise AgentCrashed("bot process closed its input") from None
        reply = self._read_reply(timeout)
        if reply.get("type") == "error":
            raise AgentFault(str(reply.get("message", "bot error"))[-600:])
        return reply

    def close(self) -> None:
        proc = self._proc
        if proc.poll() is None:
            try:
                proc.stdin.write('{"type":"quit"}\n')
                proc.stdin.flush()
            except (BrokenPipeError, OSError, ValueError):
                pass
            try:
                proc.wait(timeout=0.3)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
        for stream in (proc.stdin, proc.stdout):
            try:
                stream.close()
            except (OSError, ValueError):
                pass
        if self._log_file is not None:
            try:
                self._log_file.close()
            except OSError:
                pass
            self._log_file = None
