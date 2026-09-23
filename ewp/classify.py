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


def _is_subject_list(value) -> bool:
    return isinstance(value, (list, tuple)) and all(isinstance(s, str) and s for s in value)


def validate_view(view: EvidenceView) -> None:
    """Invalid input is refused, never evaluated.

    - Closed enums fail closed: an unknown `result` must not classify like
      `supports`, an unknown conflict `status` must not read as no
      conflict, and an unknown `polarity` must not silently drop opposition.
    - The view is bounded: every assertion and evidence item is about the
      view's proposition (or a `proposition_id:<suffix>` variant), and every
      conflict row names it. Records about another proposition are an
      adapter error, not evidence; filtering them silently would hide it.
    - `subjects` are lists of non-empty strings. A bare string would be
      iterated as characters and match on shared letters.
    - `freshness_policy_seconds` is a non-negative int (not bool);
      `degraded` is a bool; `retrieval_scope` is a string.
    """
    problems: list[str] = []
    pid = view.proposition_id
    for a in view.assertions:
        if not about_proposition(a.proposition_id, pid):
            problems.append(f"assertion {a.assertion_id}: proposition_id={a.proposition_id!r} is not {pid!r}")
    for e in view.evidence:
        if e.polarity not in POLARITIES:
            problems.append(f"evidence {e.evidence_id}: polarity={e.polarity!r}")
        if not about_proposition(e.proposition_id, pid):
            problems.append(f"evidence {e.evidence_id}: proposition_id={e.proposition_id!r} is not {pid!r}")
    for c in view.checks:
        if c.result not in CHECK_RESULTS:
            problems.append(f"check {c.check_id}: result={c.result!r}")
        if not _is_subject_list(c.subjects):
            problems.append(f"check {c.check_id}: subjects={c.subjects!r} must be a list of strings")
    for c in view.conflicts:
        if c.status not in CONFLICT_STATUSES:
            problems.append(f"conflict {c.conflict_id}: status={c.status!r}")
        if not any(about_proposition(x, pid) for x in c.proposition_ids):
            problems.append(f"conflict {c.conflict_id}: proposition_ids={list(c.proposition_ids)!r} do not name {pid!r}")
    for edge in view.lineage:
        if edge.kind not in LINEAGE_KINDS:
            problems.append(f"lineage {edge.from_id}->{edge.to_id}: kind={edge.kind!r}")
    if not _is_subject_list(view.subjects):
        problems.append(f"subjects={view.subjects!r} must be a list of strings")
    fresh = view.freshness_policy_seconds
    if type(fresh) is not int or fresh < 0:
        problems.append(f"freshness_policy_seconds={fresh!r} must be a non-negative integer")
    if type(view.degraded) is not bool:
        problems.append(f"degraded={view.degraded!r} must be a boolean")
    if not isinstance(view.retrieval_scope, str):
        problems.append(f"retrieval_scope={view.retrieval_scope!r} must be a string")
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
