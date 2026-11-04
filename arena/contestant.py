"""A contestant: one bot plus the rules for when it misbehaves.

The guard turns every way a bot can go wrong into a legal fallback
action and a recorded fault: exceptions, timeouts, crashes, garbage
replies and illegal moves. Too many faults, or exceeding the thinking
time budget, replaces the bot with an always-fold stub for the rest of
the pairing, which the scoreboard punishes naturally (about -0.75
bb/hand) without any special scoring rule.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, List, Mapping, Optional, Sequence

from .agents import Agent, AgentFault


@dataclass(frozen=True)
class Decision:
    action: str
    amount: Optional[int]
    fault: Optional[str] = None


def fallback_action(legal: Sequence[str]) -> str:
    """Check when it is free, otherwise fold."""
    return "check" if "check" in legal else "fold"


@dataclass
class Contestant:
    """Wraps an agent factory with fault accounting."""

    name: str
    factory: Callable[[], Agent]
    move_timeout: float = 1.0
    max_faults: int = 20
    faults: int = 0
    fault_log: List[str] = field(default_factory=list)
    disabled: bool = False
    disabled_reason: Optional[str] = None
    think_seconds: float = 0.0
    decisions: int = 0
    _agent: Optional[Agent] = field(default=None, repr=False)
    _stretch_think: float = 0.0
    _think_budget: Optional[float] = None

    def new_stretch(self, think_budget: Optional[float] = None) -> None:
        """Starts a fresh bot process with a fresh thinking budget.

        Called before each run of hands so a bot cannot carry memory
        from one half of a duplicate pairing into the other.
        """
        self._drop_agent()
        self._stretch_think = 0.0
        self._think_budget = think_budget

    def close(self) -> None:
        self._drop_agent()

    def record_fault(self, reason: str) -> None:
        self.faults += 1
        if len(self.fault_log) < 50:
            self.fault_log.append(reason)
        if self.faults >= self.max_faults and not self.disabled:
            self._disable(f"{self.faults} faults")

    def decide(
        self,
        state: Mapping[str, Any],
        hero_index: int,
        action_history: Sequence[Mapping[str, Any]],
    ) -> Decision:
        """Returns the bot's move, or a fallback plus the fault reason."""
        legal = list(state.get("legal_actions", ()))
        if self.disabled:
            return Decision("fold", None)

        started = time.perf_counter()
        try:
            reply = self._request(state, hero_index, action_history)
            decision = self._validate(reply, legal)
        except AgentFault as exc:
            self._drop_agent()
            reason = f"{type(exc).__name__}: {exc}"
            self.record_fault(reason)
            decision = Decision(fallback_action(legal), None, reason)
        elapsed = time.perf_counter() - started

        self.decisions += 1
        self.think_seconds += elapsed
        self._stretch_think += elapsed
        if (
            self._think_budget is not None
            and self._stretch_think > self._think_budget
            and not self.disabled
        ):
            self._disable(
                f"time budget exceeded ({self._stretch_think:.1f}s"
                f" > {self._think_budget:.1f}s)"
            )
        return decision

    def _request(self, state, hero_index, action_history):
        if self._agent is None:
            try:
                self._agent = self.factory()
            except AgentFault:
                self._disable("bot failed to start")
                raise
        return self._agent.request(
            {
                "type": "act",
                "state": state,
                "hero_index": hero_index,
                "action_history": list(action_history),
            },
            self.move_timeout,
        )

    @staticmethod
    def _validate(reply: Mapping[str, Any], legal: Sequence[str]) -> Decision:
        action = reply.get("action")
        amount = reply.get("amount")
        if not isinstance(action, str):
            raise AgentFault(f"reply has no action: {dict(reply)!r}")
        if action in ("bet", "raise_to"):
            if isinstance(amount, bool) or not isinstance(amount, int):
                raise AgentFault(f"{action} needs an integer amount")
        else:
            amount = None
        return Decision(action, amount)

    def _disable(self, reason: str) -> None:
        self.disabled = True
        self.disabled_reason = reason
        if len(self.fault_log) < 50:
            self.fault_log.append(f"DISABLED: {reason}")
        self._drop_agent()

    def _drop_agent(self) -> None:
        if self._agent is not None:
            try:
                self._agent.close()
            finally:
                self._agent = None
