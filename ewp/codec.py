"""JSON ↔ EvidenceView. Used by MCP and any store that speaks dicts.

Decoding never coerces: a falsy value is kept (freshness 0 stays 0, an
empty retrieval_scope stays empty and reads as not complete), and a value
of the wrong type is passed through so validate_view refuses it with a
clear message instead of it being silently converted.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from .classify import validate_view
from .types import (
    Assertion,
    Conflict,
    EvidenceItem,
    EvidenceView,
    LineageEdge,
    SourceRef,
    VerificationCheck,
    WarrantAxes,
    WarrantView,
)

DEFAULT_FRESHNESS_SECONDS = 86400 * 30


def _default(d: dict[str, Any], key: str, fallback: Any) -> Any:
    """Missing or null → fallback. Any present value, including 0 and "", is kept."""
    value = d.get(key)
    return fallback if value is None else value


def subjects_from(value: Any) -> Any:
    """null → (); a list → tuple; anything else (e.g. a bare string) is
    returned as-is so validation refuses it rather than iterating characters."""
    if value is None:
        return ()
    if isinstance(value, (list, tuple)):
        return tuple(value)
    return value


def content_view_id(view: EvidenceView) -> str:
    """Deterministic id for a view's content: same evidence, same id."""
    body = view.to_dict()
    body.pop("view_id", None)
    body.pop("adapter_meta", None)
    digest = hashlib.sha256(json.dumps(body, sort_keys=True, default=list).encode()).hexdigest()
    return "v-" + digest[:20]


def source_from_dict(d: dict[str, Any]) -> SourceRef:
    return SourceRef(
        source_id=str(d["source_id"]),
        lineage_id=str(d["lineage_id"]),
        origin_type=str(d["origin_type"]),
        origin_locator=str(d["origin_locator"]),
        snapshot_id=str(d["snapshot_id"]),
        content_hash=str(d["content_hash"]),
        observed_at=str(d["observed_at"]),
        extractor_id=d.get("extractor_id"),
        parent_source_id=d.get("parent_source_id"),
    )


def check_from_dict(d: dict[str, Any]) -> VerificationCheck:
    return VerificationCheck(
        check_id=str(d["check_id"]),
        method=str(d["method"]),
        scope=str(d["scope"]),
        source=source_from_dict(d["source"]),
        observed_at=str(d["observed_at"]),
        result=d["result"],
        subjects=subjects_from(d.get("subjects")),
    )


def view_from_dict(d: dict[str, Any]) -> EvidenceView:
    """Decode and validate. Raises InvalidEvidenceView on invalid input.

    A missing view_id becomes a content-derived id, so re-sending the same
    evidence names the same snapshot.
    """
    pid = str(d["proposition_id"])
    view = EvidenceView(
        view_id=str(d.get("view_id") or ""),
        proposition_id=pid,
        assertions=[
            Assertion(
                assertion_id=str(a["assertion_id"]),
                proposition_id=str(_default(a, "proposition_id", pid)),
                text=str(a["text"]),
                asserted_by=str(a["asserted_by"]),
                assertion_confidence=float(a["assertion_confidence"]),
                source=source_from_dict(a["source"]),
                asserted_at=str(a["asserted_at"]),
            )
            for a in d.get("assertions") or []
        ],
        evidence=[
            EvidenceItem(
                evidence_id=str(e["evidence_id"]),
                proposition_id=str(_default(e, "proposition_id", pid)),
                polarity=e["polarity"],
                source=source_from_dict(e["source"]),
                content=str(e["content"]),
                observed_at=str(e["observed_at"]),
            )
            for e in d.get("evidence") or []
        ],
        lineage=[
            LineageEdge(str(x.get("from_id") or x.get("from")), str(x.get("to_id") or x.get("to")), x["kind"])
            for x in d.get("lineage") or []
        ],
        conflicts=[
            Conflict(
                str(c["conflict_id"]),
                tuple(str(x) for x in c.get("proposition_ids") or []),
                c["status"],
                str(c.get("note") or ""),
            )
            for c in d.get("conflicts") or []
        ],
        checks=[check_from_dict(c) for c in d.get("checks") or []],
        omitted_sources=list(d.get("omitted_sources") or []),
        retrieval_scope=_default(d, "retrieval_scope", "complete"),
        degraded=_default(d, "degraded", False),
        freshness_policy_seconds=_default(d, "freshness_policy_seconds", DEFAULT_FRESHNESS_SECONDS),
        adapter_meta=dict(d.get("adapter_meta") or {}),
        subjects=subjects_from(d.get("subjects")),
    )
    validate_view(view)
    if not view.view_id:
        view.view_id = content_view_id(view)
    return view

def warrant_from_dict(d: dict[str, Any]) -> WarrantView:
    w = d.get("warrant") or {}
    return WarrantView(
        proposition_id=str(d["proposition_id"]),
        view_id=str(d.get("view_id") or ""),
        policy_id=str(d["policy_id"]),
        policy_version=str(d["policy_version"]),
        evaluated_at=str(d["evaluated_at"]),
        warrant=WarrantAxes(
            acceptance=w["acceptance"],
            conflict=w["conflict"],
            verification=w["verification"],
            currency=w["currency"],
            sufficiency=w["sufficiency"],
            strength=float(w.get("strength") or 0.0),
            rationale_codes=list(w.get("rationale_codes") or []),
        ),
        supporting_evidence_ids=list(d.get("supporting_evidence_ids") or []),
        opposing_evidence_ids=list(d.get("opposing_evidence_ids") or []),
        independent_lineage_count=int(d.get("independent_lineage_count") or 0),
        checks=list(d.get("checks") or []),
        freshest_check=d.get("freshest_check"),
        stale=bool(d.get("stale", False)),
        open_conflicts=list(d.get("open_conflicts") or []),
        resolved_conflicts=list(d.get("resolved_conflicts") or []),
        omitted_sources=list(d.get("omitted_sources") or []),
        derived_from=list(d.get("derived_from") or []),
        supersedes=list(d.get("supersedes") or []),
        superseded_by=list(d.get("superseded_by") or []),
        falsification_conditions=list(d.get("falsification_conditions") or []),
        protocol_version=str(d["protocol_version"]),
    )
