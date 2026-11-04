"""Smoke validation: can this bot load and play legally, on time?"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from .duel import PairingConfig, play_pairing
from .specs import contestant_from_spec


@dataclass
class ValidationReport:
    ok: bool
    message: str
    faults: List[str]


def smoke_test(
    target: Path,
    *,
    deals: int = 20,
    opponent: str = "@call",
    log_dir: Optional[Path] = None,
    move_timeout: float = 1.0,
) -> ValidationReport:
    """Plays a short duplicate match; any fault or stub fails it."""
    contestant = contestant_from_spec(
        str(target),
        log_dir=log_dir,
        move_timeout=move_timeout,
        # One fault is already a failure; stop early instead of
        # grinding through the whole match.
        max_faults=1,
    )
    sparring = contestant_from_spec(opponent)
    result = play_pairing(
        contestant,
        sparring,
        PairingConfig(
            deals=deals,
            seed=12345,
            # The strict per-move limit is what is being checked; the
            # cumulative budget is the competition's concern.
            think_budget_per_deal=60.0,
        ),
    )
    if result.faults_a or result.disabled_a:
        detail = "; ".join(result.fault_log_a[:3]) or "bot was disabled"
        return ValidationReport(False, detail, result.fault_log_a)
    if result.status != "complete":
        return ValidationReport(False, "smoke match did not finish", [])
    return ValidationReport(
        True,
        f"played {result.hands_played} hands vs {opponent} with no faults",
        [],
    )
