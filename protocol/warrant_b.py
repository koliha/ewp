"""Second evaluator. Same normative rules, different control flow.

Compares on the five axes only. Does not emit strength.
Used to test that the interchange contract is the axes, not reference-evaluator internals.
"""

from __future__ import annotations

from .classify import (
    check_verification_class,
    class_conferring_checks,
    freshest_check,
    highest_verification,
    implied_open_conflict,
    opposing_high_check,
    opposing_items,
    parse_ts,
    superseding_edges,
    supporting_items,
    validate_view,
    visible_assertions,
    visible_checks,
)
from .warrant import REFERENCE_POLICY
from .types import (
    EXTERNAL_METHODS,
    HUMAN_METHODS,
    INDIRECT_METHODS,
    EvidenceView,
    Policy,
    VerificationCheck,
)


def axes_only(view: EvidenceView, policy: Policy, evaluated_at: str) -> dict[str, str]:
    """Normative projection: five axes. No scalar."""
    if (policy.policy_id, policy.version) != REFERENCE_POLICY:
        raise ValueError(
            f"unknown policy {policy.policy_id}/{policy.version}; "
            f"this evaluator implements {REFERENCE_POLICY[0]} only"
        )
    validate_view(view)
    eval_dt = parse_ts(evaluated_at)
    assertions = visible_assertions(view, evaluated_at)
    supporting = supporting_items(view, evaluated_at)
    opposing = opposing_items(view, evaluated_at)
    checks = visible_checks(view, evaluated_at)
    open_c = [c for c in view.conflicts if c.status == "open"]
    resolved_c = [c for c in view.conflicts if c.status == "resolved"]

    if open_c or implied_open_conflict(view, evaluated_at):
        conflict = "OPEN"
    elif resolved_c:
        conflict = "RESOLVED"
    else:
        conflict = "NONE"

    verification = highest_verification(view, evaluated_at)

    stale = False
    class_checks = class_conferring_checks(view, verification, evaluated_at)
    if class_checks:
        newest = freshest_check(class_checks)
        age = (eval_dt - parse_ts(newest.observed_at)).total_seconds()
        stale = age > view.freshness_policy_seconds

    superseded = bool(superseding_edges(view))
    if superseded:
        currency = "SUPERSEDED"
    elif stale:
        currency = "STALE"
    else:
        currency = "CURRENT"

    if view.degraded or view.omitted_sources or view.retrieval_scope != "complete":
        sufficiency = "DEGRADED"
    elif not assertions and not supporting and not opposing and not checks:
        sufficiency = "INSUFFICIENT"
    else:
        sufficiency = "SUFFICIENT"

    opposing_high = opposing_high_check(view, evaluated_at)
    if not assertions and not supporting:
        acceptance = "UNACCEPTED"
    elif (
        verification in {"EXTERNAL", "HUMAN"}
        and conflict != "OPEN"
        and currency != "SUPERSEDED"
        and sufficiency == "SUFFICIENT"
        and not stale
        and not opposing_high
    ):
        acceptance = "ACCEPTED"
    else:
        acceptance = "TENTATIVE"

    return {
        "acceptance": acceptance,
        "conflict": conflict,
        "verification": verification,
        "currency": currency,
        "sufficiency": sufficiency,
        "policy_version": policy.version,
    }


def naive_trusts_method(check: VerificationCheck) -> str:
    """Broken classifier: method string alone. Must fail laundering fixtures."""
    if check.method in HUMAN_METHODS:
        return "HUMAN"
    if check.method in EXTERNAL_METHODS:
        return "EXTERNAL"
    if check.method in INDIRECT_METHODS:
        return "INDIRECT"
    return "NONE"


def naive_verification(view: EvidenceView) -> str:
    from .classify import CLASS_RANK

    verification = "NONE"
    for check in view.checks:
        cls = naive_trusts_method(check)
        if CLASS_RANK[cls] > CLASS_RANK[verification]:
            verification = cls
    return verification
