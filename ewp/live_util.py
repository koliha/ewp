"""Helpers shared by live store adapters. No third-party imports."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


EPOCH = "1970-01-01T00:00:00+00:00"
EWP_META_KEY = "ewp"


def iso(value: Any) -> str:
    if value is None or value == "":
        return EPOCH
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat()
    text = str(value).strip()
    return text or EPOCH


def observed_time(value: Any) -> str:
    """An observation time as ISO text, or "" when the store has none. Never
    the epoch: a record of unknown time must be unavailable at every T, not
    available at every T."""
    if value is None or value == "":
        return ""
    return iso(value)


def attr(obj: Any, *names: str, default: Any = None) -> Any:
    if obj is None:
        return default
    if isinstance(obj, dict):
        for name in names:
            if name in obj and obj[name] is not None:
                return obj[name]
        return default
    for name in names:
        if hasattr(obj, name):
            value = getattr(obj, name)
            if value is not None:
                return value
    return default


def as_list(value: Any) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def as_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        try:
            dumped = value.model_dump()
            if isinstance(dumped, dict):
                return dumped
        except Exception:
            pass
    if hasattr(value, "__dict__"):
        return {k: v for k, v in vars(value).items() if not k.startswith("_")}
    return {}


def unwrap_collection(payload: Any) -> list:
    """Mem0/Graphiti search payloads are inconsistently wrapped."""
    if payload is None:
        return []
    if isinstance(payload, list):
        return payload
    for key in ("results", "edges", "memories", "items", "data"):
        inner = attr(payload, key)
        if isinstance(inner, list):
            return inner
    return [payload]


def ewp_blob(container: Any) -> dict[str, Any]:
    """Pull EWP-parked fields from metadata / attributes / source_description."""
    meta = as_dict(attr(container, "metadata", "attributes", default={}))
    if isinstance(meta.get(EWP_META_KEY), dict):
        return meta[EWP_META_KEY]
    # Flat metadata written by our ingest.
    keys = (
        "lineage_id",
        "origin_type",
        "origin_locator",
        "content_hash",
        "parent_source_id",
        "proposition_id",
        "extractor_id",
        "snapshot_id",
        "kind",
        "polarity",
        "checks",
        "conflicts",
        "lineage",
        "omitted_sources",
        "degraded",
        "retrieval_scope",
        "freshness_policy_seconds",
        "check_id",
        "method",
        "scope",
        "result",
        "conflict_id",
        "proposition_ids",
        "status",
        "note",
    )
    if any(k in meta for k in keys):
        return meta
    desc = attr(container, "source_description", "sourceDescription", default=None)
    if isinstance(desc, dict):
        return desc.get(EWP_META_KEY, desc) if EWP_META_KEY in desc else desc
    if isinstance(desc, str) and desc.lstrip().startswith("{"):
        import json

        try:
            parsed = json.loads(desc)
        except json.JSONDecodeError:
            return {}
        if isinstance(parsed, dict):
            inner = parsed.get(EWP_META_KEY)
            return inner if isinstance(inner, dict) else parsed
    return {}
