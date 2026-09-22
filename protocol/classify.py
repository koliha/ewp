"""Shared primitives for the reference evaluators.

Method name alone is never enough. Origin must be on the trusted allowlist
to raise HUMAN or EXTERNAL. Scope must apply to the view.
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


def parse_ts(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


_ENTITY = re.compile(r"(?:server|host|node|device|serial)[\w.-]*", re.I)


def _entities(text: str) -> set[str]:
    return {m.group(0).lower() for m in _ENTITY.finditer(text or "")}


def scope_applies(check: VerificationCheck, view: EvidenceView) -> bool:
    """Cap only when scope names an entity family the view also uses, but a different one.

    server02 vs server01 → mismatch. dashboard_screenshot vs "serial is ABC" → applies.
    """
    scope = (check.scope or "").strip()
    if not scope:
        return True
    hay = " ".join(
        [view.proposition_id]
        + [a.text for a in view.assertions]
        + [e.content for e in view.evidence]
    )
    view_ents = _entities(hay)
    scope_ents = _entities(scope)

    def family(tok: str) -> str:
        for fam in ("server", "host", "node", "device", "serial"):
            if tok.startswith(fam):
                return fam
        return tok

    for se in scope_ents:
        fam = family(se)
        same = {v for v in view_ents if family(v) == fam}
        if same and se not in same:
            return False
    return True


def check_verification_class(check: VerificationCheck, view: EvidenceView | None = None) -> str:
    """Class of one check.

    - Origin not on TRUSTED_ORIGINS cannot raise HUMAN or EXTERNAL.
    - Endogenous origin cannot raise HUMAN or EXTERNAL.
    - result=inconclusive cannot raise HUMAN or EXTERNAL.
    - Scope that does not apply to the view cannot raise HUMAN or EXTERNAL.
    - result=opposes still classifies the check; conflict is a separate axis.
    """
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


def highest_verification(view: EvidenceView) -> str:
    verification = "NONE"
    for check in view.checks:
        cls = check_verification_class(check, view)
        if CLASS_RANK[cls] > CLASS_RANK[verification]:
            verification = cls
    return verification


def implied_open_conflict(view: EvidenceView) -> bool:
    polarities = {e.polarity for e in view.evidence}
    results = {c.result for c in view.checks}
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


def class_conferring_checks(view: EvidenceView, verification: str) -> list[VerificationCheck]:
    if verification == "NONE":
        return []
    return [c for c in view.checks if check_verification_class(c, view) == verification]


def freshest_check(checks: list[VerificationCheck]) -> VerificationCheck:
    return max(checks, key=lambda c: parse_ts(c.observed_at))


def opposing_high_check(view: EvidenceView) -> bool:
    return any(
        c.result == "opposes" and check_verification_class(c, view) in {"EXTERNAL", "HUMAN"}
        for c in view.checks
    )
