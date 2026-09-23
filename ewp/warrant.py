from __future__ import annotations

from .classify import (
    available_at,
    check_verification_class,
    class_conferring_checks,
    freshest_check,
    highest_verification,
    implied_open_conflict,
    independent_lineage_ids,
    opposing_high_check,
    opposing_items,
    parse_evaluated_at,
    parse_ts,
    superseding_edges,
    supporting_items,
    validate_view,
    visible_assertions,
    visible_checks,
)
from .types import (
    ENDOGENOUS_ORIGINS,
    EXTERNAL_METHODS,
    EvidenceView,
    Policy,
    WarrantAxes,
    WarrantView,
)
from .versions import POLICY, PROTOCOL

# Re-export: adapters and tests may import the classifier from the kernel.
__all__ = ["warrant_now", "check_verification_class"]


REFERENCE_POLICY = (POLICY, POLICY)


def warrant_now(view: EvidenceView, policy: Policy, evaluated_at: str) -> WarrantView:
    """Deterministic reference-v2 evaluator. No store I/O. No LLM.

    Raises InvalidEvidenceView for values outside the closed input enums.
    """
    if (policy.policy_id, policy.version) != REFERENCE_POLICY:
        raise ValueError(
            f"unknown policy {policy.policy_id}/{policy.version}; "
            f"this evaluator implements {POLICY} only"
        )
    validate_view(view)
    codes: list[str] = []
    eval_dt = parse_evaluated_at(evaluated_at)

    assertions = visible_assertions(view, evaluated_at)
    supporting = supporting_items(view, evaluated_at)
    opposing = opposing_items(view, evaluated_at)
    checks = visible_checks(view, evaluated_at)

    lineage_ids = independent_lineage_ids(view, evaluated_at)
    independent = len(lineage_ids)
    if any(not available_at(a.asserted_at, evaluated_at) for a in view.assertions):
        codes.append("availability.future_assertion")
    if any(not available_at(e.observed_at, evaluated_at) for e in view.evidence):
        codes.append("availability.future_evidence")

    open_c = [c for c in view.conflicts if c.status == "open"]
    resolved_c = [c for c in view.conflicts if c.status == "resolved"]
    implied = implied_open_conflict(view, evaluated_at)
    if open_c or implied:
        conflict: str = "OPEN"
        if open_c:
            codes.append("conflict.open")
        if implied and not open_c:
            codes.append("conflict.implied_polarity")
    elif resolved_c:
        conflict = "RESOLVED"
        codes.append("conflict.resolved")
    else:
        conflict = "NONE"

    if any(
        c.source.origin_type in ENDOGENOUS_ORIGINS and c.method in EXTERNAL_METHODS
        for c in view.checks
    ):
        codes.append("verification.laundered_endogenous")
    if any(not available_at(c.observed_at, evaluated_at) for c in view.checks):
        codes.append("verification.not_available_at_t")

    verification = highest_verification(view, evaluated_at)
    if verification == "HUMAN":
        codes.append("verification.human")
    elif verification == "EXTERNAL":
        codes.append("verification.external")
    elif verification == "INDIRECT":
        codes.append("verification.indirect")
    else:
        codes.append("verification.none")

    if any(c.result == "inconclusive" for c in view.checks):
        codes.append("verification.inconclusive_present")
    if any(c.result == "opposes" for c in view.checks):
        codes.append("verification.opposing_check")

    superseded_by = [e.to_id for e in superseding_edges(view)]
    supersedes = [e.to_id for e in view.lineage if e.kind == "supersedes"]
    derived_from = [e.to_id for e in view.lineage if e.kind == "derived_from"]

    # Freshness is taken from checks that actually confer the chosen class.
    # A later endogenous self-check cannot refresh EXTERNAL/HUMAN currency.
    class_checks = class_conferring_checks(view, verification, evaluated_at)
    freshest = None
    stale = False
    if class_checks:
        newest = freshest_check(class_checks)
        freshest = newest.check_id
        age = (eval_dt - parse_ts(newest.observed_at)).total_seconds()
        if age > view.freshness_policy_seconds:
            stale = True
            codes.append("currency.stale_check")
    elif checks:
        # Diagnostic only. Never feed unavailable or unparsable checks here.
        newest = freshest_check(checks)
        freshest = newest.check_id

    if superseded_by:
        currency: str = "SUPERSEDED"
        codes.append("currency.superseded")
    elif stale:
        currency = "STALE"
    else:
        currency = "CURRENT"

    if view.degraded or view.omitted_sources or view.retrieval_scope != "complete":
        sufficiency: str = "DEGRADED"
        codes.append("sufficiency.degraded")
    elif not assertions and not supporting and not opposing and not checks:
        sufficiency = "INSUFFICIENT"
        codes.append("sufficiency.none")
    else:
        sufficiency = "SUFFICIENT"

    opposing_high = opposing_high_check(view, evaluated_at)
    if not assertions and not supporting:
        acceptance: str = "UNACCEPTED"
        codes.append("acceptance.none")
    elif (
        verification in {"EXTERNAL", "HUMAN"}
        and conflict != "OPEN"
        and currency != "SUPERSEDED"
        and sufficiency == "SUFFICIENT"
        and not stale
        and not opposing_high
    ):
        acceptance = "ACCEPTED"
        codes.append("acceptance.accepted")
    else:
        acceptance = "TENTATIVE"
        codes.append("acceptance.tentative")

    # Warrant strength is policy-computed. MUST NOT use retrieval score
    # or repetition count. Independent lineage is capped so clones don't help.
    strength = 0.15
    if acceptance == "ACCEPTED":
        strength += 0.45
    elif acceptance == "TENTATIVE":
        strength += 0.15
    if verification == "HUMAN":
        strength += 0.25
    elif verification == "EXTERNAL":
        strength += 0.20
    elif verification == "INDIRECT":
        strength += 0.05
    strength += min(0.10, 0.05 * min(independent, 2))
    if conflict == "OPEN":
        strength -= 0.20
    if currency == "STALE":
        strength -= 0.15
    if currency == "SUPERSEDED":
        strength -= 0.35
    if sufficiency == "DEGRADED":
        strength -= 0.15
    if sufficiency == "INSUFFICIENT":
        strength = min(strength, 0.10)
    strength = max(0.0, min(1.0, round(strength, 4)))

    return WarrantView(
        proposition_id=view.proposition_id,
        view_id=view.view_id,
        policy_id=policy.policy_id,
        policy_version=policy.version,
        evaluated_at=evaluated_at,
        warrant=WarrantAxes(
            acceptance=acceptance,  # type: ignore[arg-type]
            conflict=conflict,  # type: ignore[arg-type]
            verification=verification,  # type: ignore[arg-type]
            currency=currency,  # type: ignore[arg-type]
            sufficiency=sufficiency,  # type: ignore[arg-type]
            strength=strength,
            rationale_codes=codes,
        ),
        supporting_evidence_ids=[e.evidence_id for e in supporting],
        opposing_evidence_ids=[e.evidence_id for e in opposing],
        independent_lineage_count=independent,
        checks=[c.check_id for c in view.checks],
        freshest_check=freshest,
        stale=stale,
        open_conflicts=[c.conflict_id for c in open_c],
        resolved_conflicts=[c.conflict_id for c in resolved_c],
        omitted_sources=list(view.omitted_sources),
        derived_from=derived_from,
        supersedes=supersedes,
        superseded_by=superseded_by,
        protocol_version=PROTOCOL,
    )
