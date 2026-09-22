"""Optional ingest checks. Classification already treats unknown origins as untrusted."""

from __future__ import annotations

from .types import EXTERNAL_METHODS, HUMAN_METHODS, INDIRECT_METHODS, TRUSTED_ORIGINS, EvidenceView

KNOWN_METHODS = EXTERNAL_METHODS | HUMAN_METHODS | INDIRECT_METHODS


def view_warnings(view: EvidenceView) -> list[str]:
    warnings: list[str] = []
    origins = {a.source.origin_type for a in view.assertions}
    origins |= {e.source.origin_type for e in view.evidence}
    origins |= {c.source.origin_type for c in view.checks}
    for origin in sorted(origins):
        if origin not in TRUSTED_ORIGINS and origin not in {
            "extract", "turn", "derived", "summary", "model_introspection", "episode"
        }:
            warnings.append(f"unknown_origin:{origin}")
    for check in view.checks:
        if check.method not in KNOWN_METHODS:
            warnings.append(f"unknown_method:{check.method}")
    return warnings
