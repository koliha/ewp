from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .types import WarrantView

ActDecision = Literal["MAY_ACT", "REQUIRE_CONFIRMATION", "DENY"]
RISK_LEVELS = frozenset({"low", "medium", "high"})


@dataclass(frozen=True)
class Action:
    action_id: str
    kind: str
    reversible: bool = True
    risk: Literal["low", "medium", "high"] = "low"


@dataclass(frozen=True)
class RiskPolicy:
    policy_id: str = "action-v0.1"
    version: str = "0.1.0"
    high_requires_accepted: bool = True
    high_requires_no_open_conflict: bool = True


def may_act(warrant: WarrantView, action: Action, risk_policy: RiskPolicy) -> ActDecision:
    """Separate gate. Epistemic state in, authorization/risk out.

    Flags on RiskPolicy are live. high_requires_no_open_conflict and
    reversible are not documentation. An unknown risk level is refused,
    not treated as a milder one. A superseded proposition is never
    acted on without confirmation.
    """
    if action.risk not in RISK_LEVELS:
        raise ValueError(f"unknown action risk {action.risk!r}; expected one of {sorted(RISK_LEVELS)}")
    w = warrant.warrant
    if w.acceptance == "UNACCEPTED":
        return "DENY"
    if action.risk == "high":
        if w.currency == "SUPERSEDED":
            return "DENY"
        if risk_policy.high_requires_accepted and w.acceptance != "ACCEPTED":
            return "DENY"
        if risk_policy.high_requires_no_open_conflict and w.conflict == "OPEN":
            return "DENY"
        if not action.reversible and w.acceptance != "ACCEPTED":
            return "DENY"
        if w.sufficiency == "DEGRADED" or w.currency == "STALE":
            return "REQUIRE_CONFIRMATION"
        return "MAY_ACT"
    if w.currency == "SUPERSEDED":
        return "REQUIRE_CONFIRMATION"
    if w.conflict == "OPEN":
        return "REQUIRE_CONFIRMATION"
    if w.sufficiency == "DEGRADED":
        return "REQUIRE_CONFIRMATION"
    if w.currency == "STALE" and action.risk != "low":
        return "REQUIRE_CONFIRMATION"
    if w.acceptance == "TENTATIVE" and action.risk != "low":
        return "REQUIRE_CONFIRMATION"
    if not action.reversible and w.acceptance != "ACCEPTED" and action.risk != "low":
        return "REQUIRE_CONFIRMATION"
    return "MAY_ACT"
