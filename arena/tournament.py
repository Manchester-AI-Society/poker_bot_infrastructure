"""The two-round tournament.

Round 1 (groups): every registered team is drawn into a group of at most
``group_size`` bots (groups are as even as possible), and each group plays a
round robin. Round 2 (finals): the best ``advance`` bots of each group play
a round robin among themselves. Nothing is published as a live standing: the
group tables are revealed when round 1 is complete, and the final table when
round 2 is.

Phases::

    registration -> drawn -> groups -> between -> finals -> done

``draw`` and the two ``start-*`` steps are taken by the organiser (they change
the stored state); ``between`` and ``done`` are reached by themselves when the
last match of a round ends. A running :class:`Runner` plays whatever the stored
state says is due, so it can be stopped and started again at any time.

Bots connect over the gateway. A pairing is played when both its teams are
connected and free. A team that is still not connected ``grace`` seconds after
its round began forfeits the matches it has not played: its side folds every
hand, which the scoring punishes exactly as it does for a crashed bot.
"""

from __future__ import annotations

import math
import os
import random
import re
import secrets
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Sequence

from . import leaderboard
from .contestant import Contestant
from .duel import PairingConfig, play_pairing
from .gateway import Gateway, hash_key
from .history import HandWriter
from .scheduler import pair_seed
from .store import Store, remote_hash

TEAM_NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")
PHASES = ("registration", "drawn", "groups", "between", "finals", "done")


class TournamentError(Exception):
    """Something the organiser asked for cannot be done in this phase."""


@dataclass(frozen=True)
class TournamentSettings:
    deals_group: int = 100
    deals_final: int = 200
    move_timeout: float = 1.0
    max_faults: int = 20
    # Per deal, per bot: the network time to the bot is part of it.
    think_budget_per_deal: float = 3.0
    time_cap_seconds: Optional[float] = 1800.0
    grace_seconds: float = 300.0
    concurrency: int = 8


def new_key() -> str:
    """A secret key for one team.

    The fixed prefix matters: a bare url-safe token can start with "-", and a
    command line then reads ``--key -abc`` as a second option (the client
    refused to start for the team that was given such a key).
    """
    return "ak_" + secrets.token_urlsafe(24)


# -- teams and keys ----------------------------------------------------------


def generate_keys(
    store: Store, names: Sequence[str], rotate: Sequence[str] = ()
) -> Dict[str, str]:
    """Creates teams and returns the NEW secret keys (team -> key).

    Only a hash of each key is kept, so a key can be shown once, when it is
    made. A team that already exists is left alone unless it is in ``rotate``,
    which gives it a new key (the old one stops working).
    """
    bad = [n for n in list(names) + list(rotate) if not TEAM_NAME.match(n)]
    if bad:
        raise TournamentError(
            "team names are lowercase letters, digits, '-' and '_' (up to "
            f"32 characters); not valid: {', '.join(sorted(set(bad)))}"
        )
    state = store.tournament()
    if state and state["phase"] not in ("registration", "drawn"):
        if [n for n in names if n not in store.remote_teams()]:
            raise TournamentError("teams cannot be added once play has begun")
    keys: Dict[str, str] = {}
    existing = store.remote_teams()
    for name in names:
        if name in existing:
            continue
        key = new_key()
        if store.add_remote_team(name, hash_key(key)):
            keys[name] = key
    for name in rotate:
        if name not in existing:
            raise TournamentError(f"no team called {name!r} to rotate")
        key = new_key()
        store.set_remote_key(name, hash_key(key))
        keys[name] = key
    if state is None and store.remote_teams():
        store.set_tournament(_blank_state())
    return keys


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


def state_of(store: Store) -> Dict[str, Any]:
    state = store.tournament()
    if state is None:
        raise TournamentError("no teams yet: run 'arena keys' first")
    return state


# -- the draw ----------------------------------------------------------------


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
    state = state_of(store)
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
    teams = sorted(store.remote_teams())
    if len(teams) < 2:
        raise TournamentError("at least two teams are needed")
    if seed is None:
        seed = secrets.randbits(32)
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
                "freeze": store.create_freeze(
                    [store.get_version(remote_hash(t)) for t in members]
                ),
            }
            for index, members in enumerate(groups)
        ],
    )
    store.set_tournament(state)
    return state


# -- phases ------------------------------------------------------------------


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
    deals = deals or TournamentSettings.deals_group
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
    freeze = store.create_freeze(
        [store.get_version(remote_hash(t)) for t in finalists]
    )
    deals = deals or TournamentSettings.deals_final
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


# -- running the matches -----------------------------------------------------


class Runner:
    """Plays what the stored tournament state says is due."""

    def __init__(
        self,
        store: Store,
        gateway: Gateway,
        settings: TournamentSettings = TournamentSettings(),
        *,
        clock: Callable[[], float] = time.time,
        log: Callable[[str], None] = print,
    ) -> None:
        self.store = store
        self.gateway = gateway
        self.settings = settings
        self._clock = clock
        self._log = log
        self._pool = ThreadPoolExecutor(
            max_workers=max(1, settings.concurrency),
            thread_name_prefix="arena-match",
        )
        self._active: Dict[int, Future] = {}
        self._busy: Dict[int, tuple] = {}
        self._worker = f"scheduler-{os.getpid()}"
        store.requeue_running()

    # -- scheduling ---------------------------------------------------------

    def step(self) -> None:
        """One pass: reap finished matches, start any that can start."""
        self._reap()
        state = self.store.tournament()
        if state is None or state["phase"] not in ("groups", "finals"):
            return
        kind = "group" if state["phase"] == "groups" else "final"
        started = state["started"].get(
            "groups" if kind == "group" else "finals", self._clock()
        )
        forfeit_open = self._clock() - started >= self.settings.grace_seconds
        connected = self.gateway.connected_teams()
        busy = {team for pair in self._busy.values() for team in pair}

        for job in self.store.jobs_of(kind):
            if job["status"] != "queued":
                continue
            if len(self._active) >= self.settings.concurrency:
                break
            a, b = self._team(job["a_hash"]), self._team(job["b_hash"])
            if a in busy or b in busy:
                continue
            absent = [t for t in (a, b) if t not in connected]
            if absent and not forfeit_open:
                continue
            if not self.store.claim_job_by_id(job["id"], self._worker):
                continue
            busy.update((a, b))
            self._busy[job["id"]] = (a, b)
            self._active[job["id"]] = self._pool.submit(
                self._play, job["id"], absent
            )
        self._reap()
        if not self._active:
            moved = settle(self.store)
            if moved:
                self._log(f"[tournament] phase is now {moved!r}")

    def _team(self, version_hash: str) -> str:
        version = self.store.get_version(version_hash)
        return version.team if version else version_hash

    def _reap(self) -> None:
        for job_id in [j for j, f in self._active.items() if f.done()]:
            future = self._active.pop(job_id)
            self._busy.pop(job_id, None)
            error = future.exception()
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

    def _contestant(self, team: str, absent: bool) -> Contestant:
        s = self.settings
        if absent:
            return Contestant(
                name=team,
                factory=lambda: None,
                disabled=True,
                disabled_reason="not connected: forfeited",
                move_timeout=s.move_timeout,
            )
        return Contestant(
            name=team,
            factory=lambda: self.gateway.agent(team),
            move_timeout=s.move_timeout,
            max_faults=s.max_faults,
        )

    def _play(self, job_id: int, absent: List[str]) -> None:
        job = self.store.get_job(job_id)
        first, second = self._team(job.a_hash), self._team(job.b_hash)
        contestants = [
            self._contestant(first, first in absent),
            self._contestant(second, second in absent),
        ]
        match_id = f"{job.kind}-{job.id}"
        for team in (first, second):
            if team not in absent:
                self.gateway.notify(
                    team,
                    {
                        "type": "match_start",
                        "match": match_id,
                        "deals": job.deals,
                    },
                )
        self._log(f"[tournament] {match_id}: {first} vs {second}")
        config = PairingConfig(
            deals=job.deals,
            seed=job.seed,
            think_budget_per_deal=self.settings.think_budget_per_deal,
            time_cap_seconds=self.settings.time_cap_seconds,
        )
        hands_rel = f"hands/{match_id}.jsonl.gz"
        try:
            with HandWriter(self.store.root / hands_rel) as writer:
                result = play_pairing(
                    contestants[0], contestants[1], config, writer.write
                )
        finally:
            for team in (first, second):
                if team not in absent:
                    self.gateway.notify(
                        team, {"type": "match_end", "match": match_id}
                    )
        data = result.to_dict()
        data["a_team"], data["b_team"] = first, second
        self.store.finish_job(job.id, data, hands_rel)


# -- status for the organiser ------------------------------------------------


def status(store: Store) -> Dict[str, Any]:
    """Plain facts about where the tournament stands (for the CLI)."""
    state = store.tournament()
    if state is None:
        return {"phase": None, "teams": sorted(store.remote_teams())}
    presence = store.presences()
    teams = {
        name: bool(presence.get(name, {}).get("connected"))
        for name in sorted(store.remote_teams())
    }
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
