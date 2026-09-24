"""JSON ↔ EvidenceView. Used by MCP and any store that speaks dicts.

What decoding does and does not do:

* Policy-sensitive fields are never coerced. Enums, `subjects`,
  `omitted_sources`, conflict `proposition_ids`, lineage endpoints,
  `freshness_policy_seconds`, `degraded`, and `retrieval_scope` are passed
  through as given, so validate_view refuses a wrong type instead of it
  being silently converted (a bare string is never iterated as characters).
* A falsy value is kept: freshness 0 stays 0, an empty retrieval_scope stays
  empty and reads as not complete. Only a missing or null field takes its
  schema default.
* Identifier and text fields (required and optional) are normalized with
  str(), and assertion_confidence with float(); a non-finite confidence is
  refused by validate_view.

`canonical_dict` is the one order-independent form of a view. Content ids,
snapshot comparison in the stores, and adapter conformance all use it.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from .classify import InvalidEvidenceView, validate_view
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


def _list_from(value: Any) -> Any:
    """null → []; a list/tuple → list; anything else is returned as-is for validation to refuse."""
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    return value


def _records(d: dict[str, Any], key: str) -> list[Any]:
    """A record array: missing or null is []; any other non-list is refused.

    `d.get(key) or []` would read `"checks": false` or `"evidence": ""` as
    empty, silently accepting a mistyped field.
    """
    value = d.get(key)
    if value is None:
        return []
    if not isinstance(value, (list, tuple)):
        raise InvalidEvidenceView(f"invalid EvidenceView: {key}={value!r} must be a list of records")
    return list(value)


def _number(value: Any) -> Any:
    """A JSON number stays a number; anything else (a string like "0.99", a
    boolean) is passed through unconverted so validation refuses it."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return value
    try:
        return float(value)
    except OverflowError:
        return value  # an integer no float can hold: validation refuses it


def _view_id(d: dict[str, Any]) -> str:
    """Absent, null, or "" means "derive from content"; any other non-id is refused."""
    value = d.get("view_id")
    if value is None or value == "":
        return ""
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise InvalidEvidenceView(f"invalid EvidenceView: view_id={value!r} must be a string")
    return str(value)


def _adapter_meta(d: dict[str, Any]) -> dict[str, Any]:
    """Non-normative, but still typed: missing or null is {}, a non-object is refused."""
    value = d.get("adapter_meta")
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise InvalidEvidenceView(f"invalid EvidenceView: adapter_meta={value!r} must be an object")
    return dict(value)


def _endpoint(d: dict[str, Any], *keys: str) -> Any:
    """First present endpoint id, as written; None when absent. Anything but a
    string is refused by validation (a number or list is not coerced)."""
    for key in keys:
        if d.get(key) is not None:
            return d[key]
    return None


def canonical_dict(view: EvidenceView, *, include_view_id: bool = True) -> dict[str, Any]:
    """Every SCHEMA.md field, independent of record order.

    Records sort by their id (unique within a valid view), lineage by
    (from, to, kind); subjects, omitted sources, and conflict participants
    are sets. adapter_meta is adapter-local and excluded.
    """
    d = view.to_dict()
    d.pop("adapter_meta", None)
    if not include_view_id:
        d.pop("view_id", None)
    for part, key in (("assertions", "assertion_id"), ("evidence", "evidence_id"), ("checks", "check_id"), ("conflicts", "conflict_id")):
        d[part] = sorted(d[part], key=lambda r: str(r[key]))
    for c in d["checks"]:
        c["subjects"] = sorted(c["subjects"])
    for c in d["conflicts"]:
        c["proposition_ids"] = sorted(c["proposition_ids"])
    d["lineage"] = sorted(d["lineage"], key=lambda e: (str(e["from_id"]), str(e["to_id"]), str(e["kind"])))
    d["subjects"] = sorted(d["subjects"])
    d["omitted_sources"] = sorted(d["omitted_sources"])
    return d


def record_identity_conflicts(stored: list[EvidenceView], new: EvidenceView) -> list[str]:
    """Within one proposition an id names one record across every snapshot.

    Returns a description of each id in `new` that a stored snapshot already
    uses for different content: an assertion, evidence item, or check id; a
    source_id with a different SourceRef; a conflict_id with different
    participants. Conflict status and note may change between snapshots.
    Stores without a shared ledger (JSON, Mem0) call this before writing;
    SQLite enforces the same rule in its ledger tables.
    """
    seen: dict[tuple[str, str], Any] = {}

    def remember(view: EvidenceView) -> list[tuple[tuple[str, str], Any]]:
        out: list[tuple[tuple[str, str], Any]] = []
        for a in view.assertions:
            out.append((("assertion", a.assertion_id), {k: v for k, v in a.__dict__.items() if k != "source"} | {"source_id": a.source.source_id}))
        for e in view.evidence:
            out.append((("evidence", e.evidence_id), {k: v for k, v in e.__dict__.items() if k != "source"} | {"source_id": e.source.source_id}))
        for c in view.checks:
            out.append((("check", c.check_id), {k: v for k, v in c.__dict__.items() if k != "source"} | {"source_id": c.source.source_id, "subjects": sorted(c.subjects)}))
        for r in [*view.assertions, *view.evidence, *view.checks]:
            out.append((("source", r.source.source_id), r.source))
        for c in view.conflicts:
            out.append((("conflict participants", c.conflict_id), sorted(c.proposition_ids)))
        return out

    for view in stored:
        for key, value in remember(view):
            seen.setdefault(key, value)
    problems = []
    for key, value in remember(new):
        if key in seen and seen[key] != value and f"{key[0]} {key[1]!r}" not in problems:
            problems.append(f"{key[0]} {key[1]!r}")
    return problems


def content_view_id(view: EvidenceView) -> str:
    """Deterministic id for a view's content: same evidence (in any order), same id."""
    body = canonical_dict(view, include_view_id=False)
    digest = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
    return "v-" + digest[:20]


def _req(d: dict[str, Any], key: str) -> Any:
    """A required field: missing or null is missing (never the string "None")."""
    value = d[key]
    if value is None:
        raise KeyError(key)
    return value


def optional_id(d: dict[str, Any], key: str) -> str | None:
    """An optional id: absent or null stays None; any other value is normalized with str()."""
    value = d.get(key)
    return None if value is None else str(value)


def source_from_dict(d: dict[str, Any]) -> SourceRef:
    return SourceRef(
        source_id=str(_req(d, "source_id")),
        lineage_id=str(_req(d, "lineage_id")),
        origin_type=str(_req(d, "origin_type")),
        origin_locator=str(_req(d, "origin_locator")),
        snapshot_id=str(_req(d, "snapshot_id")),
        content_hash=str(_req(d, "content_hash")),
        observed_at=str(_req(d, "observed_at")),
        extractor_id=optional_id(d, "extractor_id"),
        parent_source_id=optional_id(d, "parent_source_id"),
    )


def check_from_dict(d: dict[str, Any]) -> VerificationCheck:
    return VerificationCheck(
        check_id=str(_req(d, "check_id")),
        method=str(_req(d, "method")),
        scope=str(_req(d, "scope")),
        source=source_from_dict(_req(d, "source")),
        observed_at=str(_req(d, "observed_at")),
        result=_req(d, "result"),
        subjects=subjects_from(d.get("subjects")),
    )


def view_from_dict(d: dict[str, Any]) -> EvidenceView:
    """Decode and validate. Raises InvalidEvidenceView on invalid input,
    including a missing required field or a record that is not an object.

    A missing view_id becomes a content-derived id, so re-sending the same
    evidence names the same snapshot.
    """
    try:
        view = _decode_view(d)
    except InvalidEvidenceView:
        raise
    except KeyError as exc:
        raise InvalidEvidenceView(f"invalid EvidenceView: missing required field {exc}") from exc
    except (TypeError, AttributeError, ValueError) as exc:
        raise InvalidEvidenceView(f"invalid EvidenceView: malformed field ({exc})") from exc
    validate_view(view)
    if not view.view_id:
        view.view_id = content_view_id(view)
    return view


def _decode_view(d: dict[str, Any]) -> EvidenceView:
    pid = _req(d, "proposition_id")
    if not isinstance(pid, str):
        raise InvalidEvidenceView(f"invalid EvidenceView: proposition_id={pid!r} must be a string")
    view = EvidenceView(
        view_id=_view_id(d),
        proposition_id=pid,
        assertions=[
            Assertion(
                assertion_id=str(_req(a, "assertion_id")),
                proposition_id=str(_default(a, "proposition_id", pid)),
                text=str(_req(a, "text")),
                asserted_by=str(_req(a, "asserted_by")),
                assertion_confidence=_number(_req(a, "assertion_confidence")),
                source=source_from_dict(_req(a, "source")),
                asserted_at=str(_req(a, "asserted_at")),
            )
            for a in _records(d, "assertions")
        ],
        evidence=[
            EvidenceItem(
                evidence_id=str(_req(e, "evidence_id")),
                proposition_id=str(_default(e, "proposition_id", pid)),
                polarity=_req(e, "polarity"),
                source=source_from_dict(_req(e, "source")),
                content=str(_req(e, "content")),
                observed_at=str(_req(e, "observed_at")),
            )
            for e in _records(d, "evidence")
        ],
        lineage=[
            LineageEdge(_endpoint(x, "from_id"), _endpoint(x, "to_id"), _req(x, "kind"))
            for x in _records(d, "lineage")
        ],
        conflicts=[
            Conflict(
                str(_req(c, "conflict_id")),
                subjects_from(c.get("proposition_ids")),
                _req(c, "status"),
                str(c.get("note") or ""),
            )
            for c in _records(d, "conflicts")
        ],
        checks=[check_from_dict(c) for c in _records(d, "checks")],
        omitted_sources=_list_from(d.get("omitted_sources")),
        retrieval_scope=_default(d, "retrieval_scope", "complete"),
        degraded=_default(d, "degraded", False),
        freshness_policy_seconds=_default(d, "freshness_policy_seconds", DEFAULT_FRESHNESS_SECONDS),
        adapter_meta=_adapter_meta(d),
        subjects=subjects_from(d.get("subjects")),
    )
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
