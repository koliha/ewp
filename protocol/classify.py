"""Shared primitives for the reference evaluators.

Method name alone is never enough. Origin must be on the trusted allowlist
to raise HUMAN or EXTERNAL. Scope must apply to the view. A check whose
observed_at is after evaluated_at is not available at T.
"""

from __future__ import annotations

import re
from datetime import datetime

from .types import (
    ENDOGENOUS_ORIGINS,
    EXTERNAL_METHODS,
    HUMAN_METHODS,
    INDIRECT_METHODS,
    TRUSTED_ORIGINS,
    EvidenceItem,
    EvidenceView,
    VerificationCheck,
)

CLASS_RANK = {"NONE": 0, "INDIRECT": 1, "EXTERNAL": 2, "HUMAN": 3}

# Identifier-shaped tokens: legacy device family (server01) and
# generic prefix-id (customer-42, contract-123, account-7).
_ENTITY = re.compile(
    r"\b(?:(?:server|host|node|device|serial)[\w.-]*|[a-z][a-z0-9]*[-_:/][a-z0-9][\w.-]*)\b",
    re.I,
)
_KNOWN_FAMILIES = ("server", "host", "node", "device", "serial")


def parse_ts(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def available_at(observed_at: str, evaluated_at: str | None) -> bool:
    """A record observed after T is not evidence available at T."""
    if evaluated_at is None:
        return True
    return parse_ts(observed_at) <= parse_ts(evaluated_at)


def _entities(text: str) -> set[str]:
    return {m.group(0).lower() for m in _ENTITY.finditer(text or "")}


def _family(tok: str) -> str:
    low = tok.lower()
    for fam in _KNOWN_FAMILIES:
        if low.startswith(fam):
            return fam
    for sep in ("-", "_", ":", "/"):
        if sep in low:
            return low.split(sep, 1)[0]
    return low


def _view_tokens(view: EvidenceView) -> set[str]:
    tokens = {s.lower() for s in view.subjects}
    hay = " ".join(
        [view.proposition_id]
        + [a.text for a in view.assertions]
        + [e.content for e in view.evidence]
    )
    tokens |= _entities(hay)
    return tokens


def _check_tokens(check: VerificationCheck) -> set[str]:
    tokens = {s.lower() for s in check.subjects}
    tokens |= _entities(check.scope or "")
    return tokens


def scope_applies(check: VerificationCheck, view: EvidenceView) -> bool:
    """Cap when check and view name the same subject family but different ids.

    Declared `subjects` on the check or view, when present, are identity
    tokens. Otherwise the evaluator extracts identifier-shaped tokens from
    `scope` and from the view text. A scope that is only an inspection
    surface (`dashboard_screenshot`) does not cap.
    """
    scope = (check.scope or "").strip()
    if not scope and not check.subjects:
        return True

    if check.subjects and view.subjects:
        check_ids = {s.lower() for s in check.subjects}
        view_ids = {s.lower() for s in view.subjects}
        if check_ids & view_ids:
            return True
        check_fams = {_family(s) for s in check_ids}
        view_fams = {_family(s) for s in view_ids}
        if check_fams & view_fams:
            return False
        return True

    view_ents = _view_tokens(view)
    scope_ents = _check_tokens(check)
    for se in scope_ents:
        fam = _family(se)
        same = {v for v in view_ents if _family(v) == fam}
        if same and se not in same:
            return False
    return True


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


def supporting_items(view: EvidenceView) -> list[EvidenceItem]:
    return [e for e in view.evidence if e.polarity == "supports"]


def opposing_items(view: EvidenceView) -> list[EvidenceItem]:
    return [e for e in view.evidence if e.polarity == "opposes"]


def independent_lineage_ids(view: EvidenceView) -> set[str]:
    ids = {a.source.lineage_id for a in view.assertions}
    ids |= {e.source.lineage_id for e in view.evidence}
    ids |= {c.source.lineage_id for c in view.checks}
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
    return max(checks, key=lambda c: parse_ts(c.observed_at))


def opposing_high_check(view: EvidenceView, evaluated_at: str | None = None) -> bool:
    return any(
        c.result == "opposes"
        and check_verification_class(c, view, evaluated_at) in {"EXTERNAL", "HUMAN"}
        for c in view.checks
    )
