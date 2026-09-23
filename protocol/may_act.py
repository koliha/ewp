from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .types import WarrantView

ActDecision = Literal["MAY_ACT", "REQUIRE_CONFIRMATION", "DENY"]


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
    reversible are not documentation.
    """
    w = warrant.warrant
    if w.acceptance == "UNACCEPTED":
        return "DENY"
    if action.risk == "high":
        if risk_policy.high_requires_accepted and w.acceptance != "ACCEPTED":
            return "DENY"
        if risk_policy.high_requires_no_open_conflict and w.conflict == "OPEN":
            return "DENY"
        if not action.reversible and w.acceptance != "ACCEPTED":
            return "DENY"
        if w.sufficiency == "DEGRADED" or w.currency == "STALE":
            return "REQUIRE_CONFIRMATION"
        return "MAY_ACT"
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
