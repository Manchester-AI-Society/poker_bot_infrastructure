"""Turns a bot specification into a Contestant.

A spec is either ``@name`` (or just ``name``) for a built-in baseline, or a
path to a ``bot.py`` file / a bot directory containing ``bot.py``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from .agents import ProcessAgent
from .baselines import BASELINES, baseline_contestant
from .contestant import Contestant


def contestant_from_spec(
    spec: str,
    *,
    name: Optional[str] = None,
    log_name: Optional[str] = None,
    log_dir: Optional[Path] = None,
    move_timeout: float = 1.0,
    max_faults: int = 20,
    startup_timeout: float = 20.0,
) -> Contestant:
    """Builds a contestant; baselines run in-process, bots in a child."""
    target = Path(spec)
    # ``@call`` is the documented form, but PowerShell treats a leading ``@``
    # as its splat operator and silently drops the argument. So the bare
    # name works too, unless a file or folder of that name exists (a real
    # bot always wins over a baseline).
    bare_baseline = spec in BASELINES and not target.exists()
    if spec.startswith("@") or bare_baseline:
        contestant = baseline_contestant(
            spec.removeprefix("@"),
            move_timeout=move_timeout,
            max_faults=max_faults,
        )
        if name:
            contestant.name = name
        return contestant

    if not target.exists():
        raise FileNotFoundError(f"Bot not found: {spec}")
    label = name or (target.stem if target.is_file() else target.name)
    log_path = (log_dir / f"{log_name or label}.log") if log_dir else None
    return Contestant(
        name=label,
        factory=lambda: ProcessAgent(
            target, log_path=log_path, startup_timeout=startup_timeout
        ),
        move_timeout=move_timeout,
        max_faults=max_faults,
    )
