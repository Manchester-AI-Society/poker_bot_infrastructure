"""Duplicate heads-up pairings.

Every deal (a seeded shuffle) is played twice: once with bot A in seat 0
and once with bot B in seat 0, so each bot plays both positions with
both sets of hole cards. Stacks reset to the same size every hand, so a
hand's result is a pure function of the cards and the two strategies,
and card luck largely cancels within a deal.

The two halves run as separate "stretches" with freshly started bot
processes, so a bot cannot remember board cards from the first half and
use them in the mirrored deal.
"""

from __future__ import annotations

import hashlib
import math
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from .contestant import Contestant
from .stats import ci95, mean_and_se
from .table import play_hand

HandSink = Callable[[Dict[str, Any]], None]


@dataclass(frozen=True)
class PairingConfig:
    deals: int = 200
    seed: int = 0
    stack: int = 2000
    small_blind: int = 10
    big_blind: int = 20
    # Thinking-time bank per bot per half, scaled by the number of
    # deals; a bot that overdraws it is replaced by an always-fold stub.
    think_budget_per_deal: float = 0.2
    time_cap_seconds: Optional[float] = None


@dataclass
class PairingResult:
    a: str
    b: str
    deals_requested: int
    deals_completed: int
    mean_bb: Optional[float]  # bb per hand, from A's side
    se_bb: float
    ci95_bb: float
    hands_played: int
    faults_a: int
    faults_b: int
    disabled_a: Optional[str]
    disabled_b: Optional[str]
    think_a: float
    think_b: float
    elapsed: float
    status: str  # "complete" | "incomplete"
    fault_log_a: List[str] = field(default_factory=list)
    fault_log_b: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        data = dict(self.__dict__)
        for key in ("se_bb", "ci95_bb"):
            if math.isinf(data[key]):
                data[key] = None
        return data


def deal_seed(seed: int, deal: int) -> int:
    """Derives the per-deal shuffle seed."""
    digest = hashlib.sha256(f"{seed}:{deal}".encode()).digest()
    return int.from_bytes(digest[:8], "big")


def play_pairing(
    a: Contestant,
    b: Contestant,
    config: PairingConfig,
    hand_sink: Optional[HandSink] = None,
) -> PairingResult:
    """Plays ``config.deals`` duplicate deals between two contestants."""
    started = time.monotonic()
    deals = config.deals
    bb = config.big_blind
    nets: List[List[Optional[float]]] = [[None] * deals, [None] * deals]
    hands_played = 0
    incomplete = False
    budget = config.think_budget_per_deal * deals
    stacks = [config.stack, config.stack]

    try:
        for orientation in (0, 1):
            a.new_stretch(budget)
            b.new_stretch(budget)
            seats = [a, b] if orientation == 0 else [b, a]
            a_seat = orientation
            for deal in range(deals):
                if (
                    config.time_cap_seconds is not None
                    and time.monotonic() - started > config.time_cap_seconds
                ):
                    incomplete = True
                    break
                record = play_hand(
                    seats,
                    deal_seed=deal_seed(config.seed, deal),
                    hand_index=deal,
                    stacks=stacks,
                    small_blind=config.small_blind,
                    big_blind=config.big_blind,
                )
                nets[orientation][deal] = record.net[a_seat] / bb
                hands_played += 1
                if hand_sink is not None:
                    hand_sink(
                        {
                            **record.to_dict(),
                            "orientation": orientation,
                            "deal": deal,
                        }
                    )
            if incomplete:
                break
    finally:
        a.close()
        b.close()

    per_deal = [
        (first + second) / 2
        for first, second in zip(*nets)
        if first is not None and second is not None
    ]
    mean, se = mean_and_se(per_deal)
    return PairingResult(
        a=a.name,
        b=b.name,
        deals_requested=deals,
        deals_completed=len(per_deal),
        mean_bb=mean,
        se_bb=se,
        ci95_bb=ci95(se, len(per_deal)) if per_deal else float("inf"),
        hands_played=hands_played,
        faults_a=a.faults,
        faults_b=b.faults,
        disabled_a=a.disabled_reason,
        disabled_b=b.disabled_reason,
        think_a=round(a.think_seconds, 3),
        think_b=round(b.think_seconds, 3),
        elapsed=round(time.monotonic() - started, 3),
        status="incomplete" if incomplete else "complete",
        fault_log_a=list(a.fault_log),
        fault_log_b=list(b.fault_log),
    )
