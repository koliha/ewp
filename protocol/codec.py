"""JSON ↔ EvidenceView. Used by MCP and any store that speaks dicts."""

from __future__ import annotations

from typing import Any

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


def _src(d: dict[str, Any]) -> SourceRef:
    fields = SourceRef.__dataclass_fields__
    return SourceRef(**{k: d.get(k) for k in fields if k in d or fields[k].default is not fields[k].default})


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
    subjects = d.get("subjects") or ()
    return VerificationCheck(
        check_id=str(d["check_id"]),
        method=str(d["method"]),
        scope=str(d["scope"]),
        source=source_from_dict(d["source"]),
        observed_at=str(d["observed_at"]),
        result=d["result"],
        subjects=tuple(str(x) for x in subjects),
    )


def view_from_dict(d: dict[str, Any]) -> EvidenceView:
    return EvidenceView(
        view_id=str(d.get("view_id") or "mcp"),
        proposition_id=str(d["proposition_id"]),
        assertions=[
            Assertion(
                assertion_id=str(a["assertion_id"]),
                proposition_id=str(a.get("proposition_id") or d["proposition_id"]),
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
                proposition_id=str(e.get("proposition_id") or d["proposition_id"]),
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
        retrieval_scope=str(d.get("retrieval_scope") or "complete"),
        degraded=bool(d.get("degraded", False)),
        freshness_policy_seconds=int(d.get("freshness_policy_seconds") or 86400 * 30),
        adapter_meta=dict(d.get("adapter_meta") or {}),
        subjects=tuple(str(x) for x in (d.get("subjects") or ())),
    )


def warrant_from_dict(d: dict[str, Any]) -> WarrantView:
    w = d.get("warrant") or {}
    return WarrantView(
        proposition_id=str(d["proposition_id"]),
        view_id=str(d.get("view_id") or ""),
        policy_id=str(d.get("policy_id") or "reference-v1"),
        policy_version=str(d.get("policy_version") or "reference-v1"),
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
    )
