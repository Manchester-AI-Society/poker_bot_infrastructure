"""Job scheduling: queue pairings, run them in a process pool.

Ladder: every pair of *current* bot versions plays once; a new version
only creates jobs for the pairs it is part of, so the leaderboard stays
current at the cost of a few pairings per submission.

Final: after ``freeze``, every pair of the frozen versions plays a
larger match whose deals differ from any ladder deal.
"""

from __future__ import annotations

import hashlib
import itertools
import os
import shutil
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional, Sequence, Tuple

from .duel import PairingConfig, play_pairing
from .history import HandWriter
from .specs import contestant_from_spec
from .store import Store, Version
from .validate import smoke_test

HARNESS_ATTEMPTS = 2


def default_workers() -> int:
    return max(1, (os.cpu_count() or 2) - 1)


@dataclass(frozen=True)
class Settings:
    deals: int = 200
    move_timeout: float = 1.0
    max_faults: int = 20
    think_budget_per_deal: float = 0.2
    time_cap_seconds: Optional[float] = 1800.0
    workers: int = field(default_factory=default_workers)


def pair_seed(base_seed: int, kind: str, a_hash: str, b_hash: str) -> int:
    """Per-pairing seed: stable, secret to teams, distinct per kind."""
    a_hash, b_hash = sorted((a_hash, b_hash))
    digest = hashlib.sha256(
        f"{base_seed}:{kind}:{a_hash}:{b_hash}".encode()
    ).digest()
    # 62 bits: SQLite integers are signed 64-bit.
    return int.from_bytes(digest[:8], "big") & ((1 << 62) - 1)


def enqueue_ladder(store: Store, deals: int) -> int:
    """Queues every missing pairing of the current versions."""
    return _enqueue(store, "ladder", store.current_versions(), deals, None)


def enqueue_final(store: Store, freeze_id: int, deals: int) -> int:
    """Queues every pairing of a freeze's versions."""
    members = store.freeze_members(freeze_id)
    return _enqueue(store, "final", members, deals, freeze_id)


def _enqueue(
    store: Store,
    kind: str,
    versions: Sequence[Version],
    deals: int,
    freeze_id: Optional[int],
) -> int:
    created = 0
    for first, second in itertools.combinations(versions, 2):
        job_id = store.create_job(
            kind,
            first.hash,
            second.hash,
            deals,
            pair_seed(store.base_seed, kind, first.hash, second.hash),
            freeze_id,
        )
        created += job_id is not None
    return created


def freeze_submissions(
    store: Store, *, revalidate: bool = True, move_timeout: float = 1.0
) -> Tuple[int, List[Tuple[str, str]]]:
    """Snapshots the current versions for the final.

    Every version is smoke-tested again; a bot that no longer passes
    (e.g. a dependency vanished) is left out and reported.
    """
    members: List[Version] = []
    excluded: List[Tuple[str, str]] = []
    for version in store.current_versions():
        if revalidate:
            report = smoke_test(
                Path(version.path),
                log_dir=store.root / "logs" / version.team / version.hash,
                move_timeout=move_timeout,
            )
            if not report.ok:
                excluded.append((version.team, report.message))
                continue
        members.append(version)
    return store.create_freeze(members), excluded


def execute_job(root: str, job_id: int, settings: Settings) -> None:
    """Plays one queued pairing and stores its result (worker process)."""
    store = Store(root)
    job = store.get_job(job_id)
    first = store.get_version(job.a_hash)
    second = store.get_version(job.b_hash)
    if first is None or second is None:
        raise RuntimeError("job refers to an unknown bot version")

    def contestant(version: Version, opponent: Version):
        log_dir = store.root / "logs" / version.team / version.hash
        log_name = f"{job.kind}-vs-{opponent.team}"
        stale = log_dir / f"{log_name}.log"
        if stale.exists():
            stale.unlink()
        return contestant_from_spec(
            version.path,
            name=version.team,
            log_name=log_name,
            log_dir=log_dir,
            move_timeout=settings.move_timeout,
            max_faults=settings.max_faults,
        )

    config = PairingConfig(
        deals=job.deals,
        seed=job.seed,
        think_budget_per_deal=settings.think_budget_per_deal,
        time_cap_seconds=settings.time_cap_seconds,
    )
    hands_rel = f"hands/{job.kind}-{job.id}.jsonl.gz"
    for attempt in range(HARNESS_ATTEMPTS):
        try:
            with HandWriter(store.root / hands_rel) as writer:
                result = play_pairing(
                    contestant(first, second),
                    contestant(second, first),
                    config,
                    writer.write,
                )
            break
        except Exception:
            # Bot misbehaviour never reaches here (it is scored); this
            # is the harness itself failing, e.g. under heavy load.
            if attempt == HARNESS_ATTEMPTS - 1:
                raise
    data = result.to_dict()
    data["a_team"], data["b_team"] = first.team, second.team
    store.finish_job(job.id, data, hands_rel)


def run_pending(
    store: Store,
    settings: Settings,
    *,
    kinds: Sequence[str] = ("ladder", "final"),
    tick: Optional[Callable[[], None]] = None,
    on_progress: Optional[Callable[[], None]] = None,
    poll_seconds: float = 1.0,
) -> int:
    """Runs queued jobs until the queue is empty; returns jobs finished.

    ``tick`` is called every poll (use it to pick up new submissions);
    ``on_progress`` after each finished job (use it to refresh results).
    """
    finished = 0
    store.requeue_running()
    with ProcessPoolExecutor(max_workers=settings.workers) as pool:
        running = {}
        while True:
            if tick is not None:
                tick()
            while len(running) < settings.workers:
                job = store.claim_job(f"scheduler-{os.getpid()}", kinds)
                if job is None:
                    break
                future = pool.submit(
                    execute_job, str(store.root), job.id, settings
                )
                running[future] = job.id
            if not running:
                break
            done, _ = wait(
                running, timeout=poll_seconds, return_when=FIRST_COMPLETED
            )
            for future in done:
                job_id = running.pop(future)
                error = future.exception()
                if error is not None:
                    store.fail_job(job_id, repr(error))
                finished += 1
                if on_progress is not None:
                    on_progress()
    return finished


def clear_logs(store: Store, team: str) -> None:
    """Removes a team's private logs (used when starting a fresh event)."""
    shutil.rmtree(store.root / "logs" / team, ignore_errors=True)
