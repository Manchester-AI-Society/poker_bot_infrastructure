"""Leaderboard: aggregate pairing results into a ranking with CIs.

Score = mean bb/hand against the field, each opponent weighted equally.
Its standard error combines the independent per-pairing standard errors.
"""

from __future__ import annotations

import math
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from .jsonutil import dumps, write_atomic
from .stats import ci95
from .store import Store, Version

Z95 = 1.96


def compute(
    store: Store, kind: str, freeze_id: Optional[int] = None
) -> Dict[str, Any]:
    """Builds the leaderboard payload for ``ladder`` or ``final``."""
    if kind == "final":
        if freeze_id is None:
            freeze_id = store.latest_freeze()
        if freeze_id is None:
            raise ValueError("no freeze exists yet; run 'freeze' first")
        members = store.freeze_members(freeze_id)
    else:
        members = store.current_versions()

    by_hash = {version.hash: version for version in members}
    rows = [
        row
        for row in store.results(kind, freeze_id)
        if row["a_hash"] in by_hash and row["b_hash"] in by_hash
    ]

    # pair[(me, other)] = (mean, se, deals) from ``me``'s point of view
    pair: Dict[tuple, Dict[str, Any]] = {}
    for row in rows:
        mean = row["mean_bb"]
        if mean is None:
            continue
        se = row["se_bb"] if row["se_bb"] is not None else math.inf
        deals = row["deals_completed"]
        a, b = by_hash[row["a_hash"]], by_hash[row["b_hash"]]
        pair[(a.team, b.team)] = _cell(mean, se, deals, row)
        pair[(b.team, a.team)] = _cell(-mean, se, deals, row, swap=True)

    teams = []
    for version in members:
        teams.append(_team_entry(version, members, pair))
    teams.sort(
        key=lambda t: (t["score"] is None, -(t["score"] or 0), t["team"])
    )
    for index, team in enumerate(teams, start=1):
        team["rank"] = index
    for upper, lower in zip(teams, teams[1:]):
        upper["tied_with_next"] = _overlaps(upper, lower)
    if teams:
        teams[-1]["tied_with_next"] = False

    names = [version.team for version in members]
    total_pairs = len(members) * (len(members) - 1) // 2
    return {
        "kind": kind,
        "provisional": kind != "final",
        "freeze_id": freeze_id,
        "generated_at": time.time(),
        "pairs_total": total_pairs,
        "pairs_done": len(pair) // 2,
        # The last finished timed cycle, or None when not cycling.
        "cycle": store.cycle_done() if kind == "ladder" else None,
        "teams": teams,
        "matrix": {
            me: {
                other: (
                    None
                    if (me, other) not in pair
                    else {
                        "mean_bb": pair[(me, other)]["mean_bb"],
                        "ci95_bb": pair[(me, other)]["ci95_bb"],
                    }
                )
                for other in names
                if other != me
            }
            for me in names
        },
    }


def _cell(
    mean: float, se: float, deals: int, row: Dict[str, Any], swap: bool = False
) -> Dict[str, Any]:
    faults_key = "faults_b" if swap else "faults_a"
    disabled_key = "disabled_b" if swap else "disabled_a"
    think_key = "think_b" if swap else "think_a"
    return {
        "mean_bb": mean,
        "se_bb": se,
        "ci95_bb": ci95(se, deals) if deals else math.inf,
        "deals": deals,
        "faults": row[faults_key],
        "disabled": row[disabled_key],
        "think": row[think_key],
        "status": row["status"],
        "job_id": row["job_id"],
    }


def _team_entry(
    version: Version, members: List[Version], pair: Dict[tuple, Any]
) -> Dict[str, Any]:
    cells = {
        other.team: pair[(version.team, other.team)]
        for other in members
        if other.hash != version.hash and (version.team, other.team) in pair
    }
    wins = draws = losses = 0
    for cell in cells.values():
        half = cell["ci95_bb"]
        if cell["mean_bb"] - half > 0:
            wins += 1
        elif cell["mean_bb"] + half < 0:
            losses += 1
        else:
            draws += 1

    score: Optional[float] = None
    ci: Optional[float] = None
    if cells:
        score = sum(c["mean_bb"] for c in cells.values()) / len(cells)
        variances = [c["se_bb"] ** 2 for c in cells.values()]
        if all(math.isfinite(v) for v in variances):
            ci = Z95 * math.sqrt(sum(variances)) / len(cells)
    return {
        "team": version.team,
        "version": version.hash,
        "score": score,
        "ci95": ci,
        "score_mbb": None if score is None else score * 1000,
        "wins": wins,
        "draws": draws,
        "losses": losses,
        "opponents_played": len(cells),
        "opponents_expected": len(members) - 1,
        "faults": sum(c["faults"] for c in cells.values()),
        "disabled_in": sorted(
            name for name, c in cells.items() if c["disabled"]
        ),
        "incomplete": sorted(
            name for name, c in cells.items() if c["status"] != "complete"
        ),
        "think_seconds": round(sum(c["think"] for c in cells.values()), 1),
        "tied_with_next": False,
    }


def _overlaps(upper: Dict[str, Any], lower: Dict[str, Any]) -> bool:
    """True when the score gap is within combined noise."""
    if None in (upper["score"], lower["score"]):
        return False
    if upper["ci95"] is None or lower["ci95"] is None:
        return True
    gap = upper["score"] - lower["score"]
    return gap < math.hypot(upper["ci95"], lower["ci95"])


def write_json(board: Dict[str, Any], path: Path) -> None:
    """Writes the payload atomically, as valid JSON, for a frontend."""
    write_atomic(path, dumps(board, indent=2))


def format_table(board: Dict[str, Any]) -> str:
    """Plain-text leaderboard for the terminal."""
    title = "FINAL" if board["kind"] == "final" else "LADDER (provisional)"
    lines = [
        f"{title}   pairings {board['pairs_done']}/{board['pairs_total']}",
        f"{'#':>2}  {'team':<20} {'bb/hand':>9} {'+/-':>7}  "
        f"{'W-D-L':>8}  {'faults':>6}",
    ]
    for team in board["teams"]:
        score = "n/a" if team["score"] is None else f"{team['score']:+.3f}"
        ci = "n/a" if team["ci95"] is None else f"{team['ci95']:.3f}"
        record = f"{team['wins']}-{team['draws']}-{team['losses']}"
        tie = " ~" if team["tied_with_next"] else ""
        lines.append(
            f"{team['rank']:>2}  {team['team']:<20} {score:>9} {ci:>7}  "
            f"{record:>8}  {team['faults']:>6}{tie}"
        )
    lines.append("~ = statistically tied with the team below")
    return "\n".join(lines)
