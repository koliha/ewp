"""Shared primitives for the reference evaluators.

Method name alone is never enough. Origin must be on the trusted allowlist
to raise HUMAN or EXTERNAL. Scope must apply to the view. A check whose
observed_at is after evaluated_at is not available at T.
"""

from __future__ import annotations

from datetime import datetime, timezone

from .types import (
    CHECK_RESULTS,
    CONFLICT_STATUSES,
    ENDOGENOUS_ORIGINS,
    EXTERNAL_METHODS,
    HUMAN_METHODS,
    INDIRECT_METHODS,
    LINEAGE_KINDS,
    POLARITIES,
    TRUSTED_ORIGINS,
    EvidenceItem,
    EvidenceView,
    LineageEdge,
    VerificationCheck,
)

CLASS_RANK = {"NONE": 0, "INDIRECT": 1, "EXTERNAL": 2, "HUMAN": 3}


class InvalidEvidenceView(ValueError):
    """The view carries a value outside a closed enum. Refuse; do not evaluate."""


def validate_view(view: EvidenceView) -> None:
    """Closed enums fail closed.

    An unknown `result` must not classify like `supports`, an unknown
    conflict `status` must not read as no conflict, and an unknown
    `polarity` must not silently drop opposition. The view is refused.
    """
    problems: list[str] = []
    for e in view.evidence:
        if e.polarity not in POLARITIES:
            problems.append(f"evidence {e.evidence_id}: polarity={e.polarity!r}")
    for c in view.checks:
        if c.result not in CHECK_RESULTS:
            problems.append(f"check {c.check_id}: result={c.result!r}")
    for c in view.conflicts:
        if c.status not in CONFLICT_STATUSES:
            problems.append(f"conflict {c.conflict_id}: status={c.status!r}")
    for edge in view.lineage:
        if edge.kind not in LINEAGE_KINDS:
            problems.append(f"lineage {edge.from_id}->{edge.to_id}: kind={edge.kind!r}")
    if not isinstance(view.freshness_policy_seconds, int) or view.freshness_policy_seconds < 0:
        problems.append(f"freshness_policy_seconds={view.freshness_policy_seconds!r}")
    if problems:
        raise InvalidEvidenceView("invalid EvidenceView: " + "; ".join(problems))


def parse_ts(ts: str) -> datetime:
    """Parse an instant. Naive values are UTC. Result is always aware."""
    text = (ts or "").strip().replace("Z", "+00:00")
    if not text:
        raise ValueError("empty timestamp")
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def available_at(observed_at: str, evaluated_at: str | None) -> bool:
    """A record observed after T is not evidence available at T.

    Missing or unparsable timestamps do not crash the evaluator; they
    are treated as not available.
    """
    if not observed_at:
        return False
    if evaluated_at is None:
        return True
    try:
        return parse_ts(observed_at) <= parse_ts(evaluated_at)
    except (ValueError, TypeError):
        return False


def scope_applies(check: VerificationCheck, view: EvidenceView) -> bool:
    """Identity is declared `subjects[]` only, compared as exact ids.

    - Check and view both declare subjects: applies iff they share one.
    - Check declares subjects, view does not: does not apply.
    - View declares subjects, check does not: does not apply. Omitting
      subjects is not a way around the binding.
    - Neither declares subjects: applies.

    `scope` is an inspection surface (`dashboard_screenshot`, a query
    name), never scraped for identifiers. There is no family inference.
    """
    check_ids = {s.lower() for s in check.subjects}
    view_ids = {s.lower() for s in view.subjects}
    if not check_ids and not view_ids:
        return True
    return bool(check_ids & view_ids)


def check_verification_class(
    check: VerificationCheck,
    view: EvidenceView | None = None,
    evaluated_at: str | None = None,
) -> str:
    """Class of one check.

    - Not available at evaluated_at → NONE.
    - Origin not on TRUSTED_ORIGINS cannot raise HUMAN or EXTERNAL.
    - Endogenous origin cannot raise HUMAN or EXTERNAL.
    - result=inconclusive cannot raise HUMAN or EXTERNAL.
    - Scope that does not apply to the view cannot raise HUMAN or EXTERNAL.
    - result=opposes still classifies the check; conflict is a separate axis.
    """
    if not available_at(check.observed_at, evaluated_at):
        return "NONE"

    origin = check.source.origin_type
    endogenous = origin in ENDOGENOUS_ORIGINS
    trusted = origin in TRUSTED_ORIGINS
    inconclusive = check.result == "inconclusive"

    if check.method in HUMAN_METHODS:
        cls = "HUMAN" if trusted and not endogenous else "INDIRECT"
    elif check.method in EXTERNAL_METHODS:
        cls = "EXTERNAL" if trusted and not endogenous else "INDIRECT"
    elif check.method in INDIRECT_METHODS:
        cls = "INDIRECT"
    else:
        cls = "NONE"

    if view is not None and not scope_applies(check, view) and CLASS_RANK[cls] >= CLASS_RANK["EXTERNAL"]:
        cls = "INDIRECT"

    if inconclusive and CLASS_RANK[cls] >= CLASS_RANK["EXTERNAL"]:
        return "INDIRECT"
    return cls


def highest_verification(view: EvidenceView, evaluated_at: str | None = None) -> str:
    verification = "NONE"
    for check in view.checks:
        cls = check_verification_class(check, view, evaluated_at)
        if CLASS_RANK[cls] > CLASS_RANK[verification]:
            verification = cls
    return verification


def implied_open_conflict(view: EvidenceView, evaluated_at: str | None = None) -> bool:
    evidence = [e for e in view.evidence if available_at(e.observed_at, evaluated_at)]
    checks = [c for c in view.checks if available_at(c.observed_at, evaluated_at)]
    polarities = {e.polarity for e in evidence}
    results = {c.result for c in checks}
    has_support = "supports" in polarities or "supports" in results
    has_oppose = "opposes" in polarities or "opposes" in results
    return has_support and has_oppose


def about_proposition(node_id: str, proposition_id: str) -> bool:
    """A lineage endpoint names this proposition or one of its variants.

    Variants use the `proposition_id:<suffix>` convention
    (`P-server01-os:2019`). Any other id is a different proposition.
    """
    return node_id == proposition_id or node_id.startswith(proposition_id + ":")


def superseding_edges(view: EvidenceView) -> list[LineageEdge]:
    """`superseded_by` edges whose from_id is this proposition (or a variant).

    An unrelated edge that leaked into the bounded view does not
    supersede the proposition under evaluation.
    """
    return [
        e
        for e in view.lineage
        if e.kind == "superseded_by" and about_proposition(e.from_id, view.proposition_id)
    ]


def visible_assertions(view: EvidenceView, evaluated_at: str | None = None):
    return [a for a in view.assertions if available_at(a.asserted_at, evaluated_at)]


def supporting_items(view: EvidenceView, evaluated_at: str | None = None) -> list[EvidenceItem]:
    return [
        e
        for e in view.evidence
        if e.polarity == "supports" and available_at(e.observed_at, evaluated_at)
    ]


def opposing_items(view: EvidenceView, evaluated_at: str | None = None) -> list[EvidenceItem]:
    return [
        e
        for e in view.evidence
        if e.polarity == "opposes" and available_at(e.observed_at, evaluated_at)
    ]


def visible_checks(view: EvidenceView, evaluated_at: str | None = None) -> list[VerificationCheck]:
    return [c for c in view.checks if available_at(c.observed_at, evaluated_at)]


def independent_lineage_ids(view: EvidenceView, evaluated_at: str | None = None) -> set[str]:
    ids = {a.source.lineage_id for a in visible_assertions(view, evaluated_at)}
    ids |= {e.source.lineage_id for e in supporting_items(view, evaluated_at)}
    ids |= {e.source.lineage_id for e in opposing_items(view, evaluated_at)}
    ids |= {c.source.lineage_id for c in visible_checks(view, evaluated_at)}
    return ids


def class_conferring_checks(
    view: EvidenceView,
    verification: str,
    evaluated_at: str | None = None,
) -> list[VerificationCheck]:
    if verification == "NONE":
        return []
    return [
        c
        for c in view.checks
        if check_verification_class(c, view, evaluated_at) == verification
    ]


def freshest_check(checks: list[VerificationCheck]) -> VerificationCheck:
    """Newest by instant. Callers pass only checks available at T, which
    are guaranteed to have parseable timestamps."""
    return max(checks, key=lambda c: parse_ts(c.observed_at))


def opposing_high_check(view: EvidenceView, evaluated_at: str | None = None) -> bool:
    return any(
        c.result == "opposes"
        and check_verification_class(c, view, evaluated_at) in {"EXTERNAL", "HUMAN"}
        for c in view.checks
    )
