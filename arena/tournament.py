"""The two-round tournament.

Round 1 (groups): every team that handed in a working bot is drawn into a
group of at most ``group_size`` bots (groups are as even as possible), and
each group plays a round robin. Round 2 (finals): the best ``advance`` bots of
each group play a round robin among themselves. Nothing is published as a live
standing: the group tables are revealed when round 1 is complete, and the
final table when round 2 is.

Phases::

    registration -> drawn -> groups -> between -> finals -> done

(``registration`` is the time the form is open and bots are being imported.)
``draw`` and the two ``start-*`` steps are taken by the organiser (they change
the stored state); ``between`` and ``done`` are reached by themselves when the
last match of a round ends. A running :class:`Runner` plays whatever the stored
state says is due, so it can be stopped and started again at any time.

The bots are the versions imported from the teams' submission zips and run on
this machine, as child processes, under the same time limits and fault rules
as everywhere else in the arena.
"""

from __future__ import annotations

import math
import os
import random
import secrets
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Sequence

from . import leaderboard
from .contestant import Contestant
from .duel import PairingConfig, play_pairing
from .history import HandWriter
from .scheduler import default_workers, pair_seed
from .specs import contestant_from_spec
from .store import Store

PHASES = ("registration", "drawn", "groups", "between", "finals", "done")


class TournamentError(Exception):
    """Something the organiser asked for cannot be done in this phase."""


@dataclass(frozen=True)
class TournamentSettings:
    move_timeout: float = 1.0
    max_faults: int = 20
    # Per deal, per half: how long a bot may think in total.
    think_budget_per_deal: float = 0.2
    time_cap_seconds: Optional[float] = 1800.0
    # Matches played at the same time (each runs two bot processes).
    concurrency: int = max(1, default_workers() // 2)


def _blank_state() -> Dict[str, Any]:
    return {
        "phase": "registration",
        "seed": None,
        "group_size": 8,
        "advance": 2,
        "groups": [],
        "finalists": [],
        "finals_freeze": None,
        "deals": {},
        "started": {},
        "champion": None,
    }


def ensure_tournament(store: Store) -> None:
    """Starts a tournament (in its submissions phase) if there is none."""
    if store.tournament() is None:
        store.set_tournament(_blank_state())


def state_of(store: Store) -> Dict[str, Any]:
    state = store.tournament()
    if state is None:
        raise TournamentError(
            "nothing to run yet: import the submissions first "
            "('arena import FOLDER')"
        )
    return state


def team_names(store: Store) -> List[str]:
    """Teams that have a working bot, sorted."""
    return sorted(v.team for v in store.current_versions())


def remove_team(store: Store, team: str) -> None:
    """Takes a team out before the draw (a disqualification, a mistake)."""
    state = store.tournament() or _blank_state()
    if state["phase"] != "registration":
        raise TournamentError("teams can only be removed before the draw")
    if team not in team_names(store):
        raise TournamentError(f"there is no team called {team!r}")
    store.unset_current(team)


# -- the draw -----------------------------


def balanced_sizes(count: int, largest: int) -> List[int]:
    """Group sizes as even as possible with none above ``largest``."""
    groups = max(1, math.ceil(count / largest))
    base, extra = divmod(count, groups)
    return [base + 1] * extra + [base] * (groups - extra)


def group_name(index: int) -> str:
    return chr(ord("A") + index) if index < 26 else str(index + 1)


def draw_groups(
    teams: Sequence[str], group_size: int, seed: int
) -> List[List[str]]:
    """A reproducible random draw into balanced groups."""
    shuffled = sorted(teams)
    random.Random(seed).shuffle(shuffled)
    groups, start = [], 0
    for size in balanced_sizes(len(shuffled), group_size):
        groups.append(sorted(shuffled[start : start + size]))
        start += size
    return groups


def draw(
    store: Store,
    *,
    group_size: int = 8,
    advance: int = 2,
    seed: Optional[int] = None,
    redo: bool = False,
) -> Dict[str, Any]:
    """Draws the groups (round 1). Allowed until the groups start playing."""
    state = store.tournament() or _blank_state()
    if state["phase"] not in ("registration", "drawn"):
        raise TournamentError(
            f"the draw is final once round 1 has started (phase: "
            f"{state['phase']})"
        )
    if state["phase"] == "drawn" and not redo:
        raise TournamentError("already drawn; use --redo to draw again")
    if group_size < 2:
        raise TournamentError("--group-size must be at least 2")
    if advance < 1:
        raise TournamentError("--advance must be at least 1")
    teams = team_names(store)
    if len(teams) < 2:
        raise TournamentError(
            "at least two teams with a working bot are needed "
            f"({len(teams)} so far)"
        )
    if seed is None:
        seed = secrets.randbits(32)
    by_team = {v.team: v for v in store.current_versions()}
    groups = draw_groups(teams, group_size, seed)
    state.update(
        phase="drawn",
        seed=seed,
        group_size=group_size,
        advance=advance,
        groups=[
            {
                "name": group_name(index),
                "teams": members,
                "freeze": store.create_freeze([by_team[t] for t in members]),
            }
            for index, members in enumerate(groups)
        ],
    )
    store.set_tournament(state)
    return state


# -- phases -----------------------------


def _create_jobs(store: Store, kind: str, freeze: int, deals: int) -> int:
    members = store.freeze_members(freeze)
    made = 0
    for i, first in enumerate(members):
        for second in members[i + 1 :]:
            job = store.create_job(
                kind,
                first.hash,
                second.hash,
                deals,
                pair_seed(
                    store.base_seed,
                    f"{kind}{freeze}",
                    first.hash,
                    second.hash,
                ),
                freeze,
            )
            made += job is not None
    return made


def start_groups(store: Store, deals: Optional[int] = None) -> int:
    """Begins round 1: queues every pairing of every group."""
    state = state_of(store)
    if state["phase"] != "drawn":
        raise TournamentError(
            f"draw the groups first (phase is {state['phase']!r})"
        )
    deals = deals or 100
    made = sum(
        _create_jobs(store, "group", g["freeze"], deals)
        for g in state["groups"]
    )
    state["phase"] = "groups"
    state["deals"]["group"] = deals
    state["started"]["groups"] = time.time()
    store.set_tournament(state)
    return made


def qualifiers(store: Store, state: Dict[str, Any]) -> List[str]:
    """The best ``advance`` teams of each group, group by group."""
    chosen: List[str] = []
    for group in state["groups"]:
        board = leaderboard.compute(store, "group", group["freeze"])
        chosen += [t["team"] for t in board["teams"][: state["advance"]]]
    return chosen


def cut_ties(store: Store, state: Dict[str, Any]) -> List[str]:
    """Groups where the last qualifier cannot be told from the first out."""
    notes = []
    for group in state["groups"]:
        board = leaderboard.compute(store, "group", group["freeze"])
        teams = board["teams"]
        cut = state["advance"]
        if len(teams) > cut and teams[cut - 1]["tied_with_next"]:
            notes.append(
                f"group {group['name']}: {teams[cut - 1]['team']} and "
                f"{teams[cut]['team']} are statistically tied for the last "
                "place"
            )
    return notes


def start_finals(store: Store, deals: Optional[int] = None) -> int:
    """Begins round 2: queues every pairing among the qualifiers."""
    state = state_of(store)
    if state["phase"] != "between":
        raise TournamentError(
            "the finals start once every group match is played "
            f"(phase is {state['phase']!r})"
        )
    finalists = state["finalists"]
    if len(finalists) < 2:
        raise TournamentError("fewer than two teams qualified")
    by_team = {v.team: v for v in store.current_versions()}
    freeze = store.create_freeze([by_team[t] for t in finalists])
    deals = deals or 200
    made = _create_jobs(store, "final", freeze, deals)
    state.update(phase="finals", finals_freeze=freeze)
    state["deals"]["final"] = deals
    state["started"]["finals"] = time.time()
    store.set_tournament(state)
    return made


def settle(store: Store) -> Optional[str]:
    """Moves a finished round on; returns the new phase if it changed."""
    state = store.tournament()
    if state is None or state["phase"] not in ("groups", "finals"):
        return None
    kind = "group" if state["phase"] == "groups" else "final"
    jobs = store.jobs_of(kind)
    if not jobs or any(j["status"] != "done" for j in jobs):
        return None
    if kind == "group":
        state["finalists"] = qualifiers(store, state)
        state["phase"] = "between"
    else:
        board = leaderboard.compute(store, "final", state["finals_freeze"])
        state["champion"] = (
            board["teams"][0]["team"] if board["teams"] else None
        )
        state["phase"] = "done"
    store.set_tournament(state)
    return state["phase"]


def revealed(state: Optional[Dict[str, Any]]) -> Dict[str, bool]:
    """What the public site may show: results only after a round is over."""
    phase = state["phase"] if state else "registration"
    return {
        "groups": phase in ("between", "finals", "done"),
        "finals": phase == "done",
    }


# -- running the matches -----------------------------


class Runner:
    """Plays what the stored tournament state says is due."""

    def __init__(
        self,
        store: Store,
        settings: Optional[TournamentSettings] = None,
        *,
        log: Callable[[str], None] = print,
    ) -> None:
        self.store = store
        self.settings = settings or TournamentSettings()
        self._log = log
        self._pool = ThreadPoolExecutor(
            max_workers=max(1, self.settings.concurrency),
            thread_name_prefix="arena-match",
        )
        self._active: Dict[int, Future] = {}
        self._worker = f"scheduler-{os.getpid()}"
        store.requeue_running()

    def step(self) -> None:
        """One pass: reap finished matches, start any that are due."""
        self._reap()
        state = self.store.tournament()
        if state is None or state["phase"] not in ("groups", "finals"):
            return
        kind = "group" if state["phase"] == "groups" else "final"
        for job in self.store.jobs_of(kind):
            if job["status"] != "queued":
                continue
            if len(self._active) >= self.settings.concurrency:
                break
            if not self.store.claim_job_by_id(job["id"], self._worker):
                continue
            self._active[job["id"]] = self._pool.submit(self._play, job["id"])
        self._reap()
        if not self._active:
            moved = settle(self.store)
            if moved:
                self._log(f"[tournament] phase is now {moved!r}")

    def _reap(self) -> None:
        for job_id in [j for j, f in self._active.items() if f.done()]:
            error = self._active.pop(job_id).exception()
            if error is not None:
                self.store.fail_job(job_id, repr(error))
                self._log(f"[tournament] match {job_id} failed: {error!r}")

    def idle(self) -> bool:
        return not self._active

    def run(self, stop: threading.Event, interval: float = 0.5) -> None:
        while not stop.is_set():
            self.step()
            stop.wait(interval)
        self.close()

    def close(self) -> None:
        self._pool.shutdown(wait=True, cancel_futures=True)

    # -- one match -----------------------------------------------------------

    def _contestant(self, version, opponent: str, kind: str) -> Contestant:
        s = self.settings
        return contestant_from_spec(
            version.path,
            name=version.team,
            log_name=f"{kind}-vs-{opponent}",
            log_dir=self.store.root / "logs" / version.team / version.hash,
            move_timeout=s.move_timeout,
            max_faults=s.max_faults,
        )

    def _play(self, job_id: int) -> None:
        job = self.store.get_job(job_id)
        first = self.store.get_version(job.a_hash)
        second = self.store.get_version(job.b_hash)
        if first is None or second is None:
            raise RuntimeError("a match refers to an unknown bot version")
        match_id = f"{job.kind}-{job.id}"
        self._log(f"[tournament] {match_id}: {first.team} vs {second.team}")
        config = PairingConfig(
            deals=job.deals,
            seed=job.seed,
            think_budget_per_deal=self.settings.think_budget_per_deal,
            time_cap_seconds=self.settings.time_cap_seconds,
        )
        hands_rel = f"hands/{match_id}.jsonl.gz"
        with HandWriter(self.store.root / hands_rel) as writer:
            result = play_pairing(
                self._contestant(first, second.team, job.kind),
                self._contestant(second, first.team, job.kind),
                config,
                writer.write,
            )
        data = result.to_dict()
        data["a_team"], data["b_team"] = first.team, second.team
        self.store.finish_job(job.id, data, hands_rel)


# -- status for the organiser -----------------------------


def status(store: Store) -> Dict[str, Any]:
    """Plain facts about where the tournament stands (for the CLI)."""
    state = store.tournament()
    teams = team_names(store)
    if state is None:
        return {"phase": "registration", "teams": teams, "matches": {}}
    counts: Dict[str, Dict[str, int]] = {}
    for kind in ("group", "final"):
        for job in store.jobs_of(kind):
            bucket = counts.setdefault(kind, {})
            bucket[job["status"]] = bucket.get(job["status"], 0) + 1
    return {
        "phase": state["phase"],
        "teams": teams,
        "groups": state["groups"],
        "finalists": state["finalists"],
        "champion": state["champion"],
        "matches": counts,
    }
