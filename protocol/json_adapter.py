"""Directory-of-JSON evidence store.

Deliberately does *not* mirror the SQLite schema. Propositions nest
observations, verification_history, and a source_graph. The adapter's
only job is to flatten that into EvidenceView.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .types import (
    Assertion,
    Conflict,
    EvidenceItem,
    EvidenceView,
    LineageEdge,
    SourceRef,
    VerificationCheck,
)


def _src(d: dict[str, Any]) -> SourceRef:
    return SourceRef(
        source_id=d["source_id"],
        lineage_id=d["lineage_id"],
        origin_type=d["origin_type"],
        origin_locator=d["origin_locator"],
        snapshot_id=d["snapshot_id"],
        content_hash=d["content_hash"],
        observed_at=d["observed_at"],
        extractor_id=d.get("extractor_id"),
        parent_source_id=d.get("parent_source_id"),
    )


class JsonFileAdapter:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _pdir(self, proposition_id: str) -> Path:
        safe = proposition_id.replace("/", "_")
        d = self.root / "propositions" / safe
        d.mkdir(parents=True, exist_ok=True)
        return d

    def load_view(self, view: EvidenceView) -> None:
        """Persist using a nested document shape, not SQLite tables."""
        d = self._pdir(view.proposition_id)
        doc = {
            "claim": view.proposition_id,
            "view_meta": {
                "view_id": view.view_id,
                "freshness_policy_seconds": view.freshness_policy_seconds,
                "retrieval_scope": view.retrieval_scope,
                "degraded": view.degraded,
                "omitted_sources": view.omitted_sources,
                "subjects": list(view.subjects),
            },
            "observations": [
                {
                    "kind": "assertion",
                    "id": a.assertion_id,
                    "text": a.text,
                    "asserted_by": a.asserted_by,
                    "how_sure_they_sounded": a.assertion_confidence,
                    "when": a.asserted_at,
                    "source": a.source.__dict__,
                }
                for a in view.assertions
            ]
            + [
                {
                    "kind": "snippet",
                    "id": e.evidence_id,
                    "side": e.polarity,
                    "content": e.content,
                    "when": e.observed_at,
                    "source": e.source.__dict__,
                }
                for e in view.evidence
            ],
            "verification_history": [
                {
                    "id": c.check_id,
                    "how": c.method,
                    "what_was_inspected": c.scope,
                    "when": c.observed_at,
                    "outcome": c.result,
                    "subjects": list(c.subjects),
                    "source": c.source.__dict__,
                }
                for c in view.checks
            ],
            "disputes": [
                {
                    "id": c.conflict_id,
                    "about": list(c.proposition_ids),
                    "open": c.status == "open",
                    "note": c.note,
                }
                for c in view.conflicts
            ],
            "source_graph": [
                {"from": e.from_id, "to": e.to_id, "rel": e.kind} for e in view.lineage
            ],
        }
        (d / "bundle.json").write_text(json.dumps(doc, indent=2, sort_keys=True))

    def get_view(
        self,
        proposition_id: str,
        view_id: str,
        *,
        omitted_sources: list[str] | None = None,
        retrieval_scope: str | None = None,
        degraded: bool | None = None,
        freshness_policy_seconds: int | None = None,
    ) -> EvidenceView:
        path = self._pdir(proposition_id) / "bundle.json"
        doc = json.loads(path.read_text())
        meta = doc.get("view_meta", {})
        assertions: list[Assertion] = []
        evidence: list[EvidenceItem] = []
        for obs in doc.get("observations", []):
            source = _src(obs["source"])
            if obs["kind"] == "assertion":
                assertions.append(
                    Assertion(
                        assertion_id=obs["id"],
                        proposition_id=proposition_id,
                        text=obs["text"],
                        asserted_by=obs["asserted_by"],
                        assertion_confidence=obs["how_sure_they_sounded"],
                        source=source,
                        asserted_at=obs["when"],
                    )
                )
            elif obs["kind"] == "snippet":
                evidence.append(
                    EvidenceItem(
                        evidence_id=obs["id"],
                        proposition_id=proposition_id,
                        polarity=obs["side"],
                        source=source,
                        content=obs["content"],
                        observed_at=obs["when"],
                    )
                )
        checks = [
            VerificationCheck(
                check_id=v["id"],
                method=v["how"],
                scope=v["what_was_inspected"],
                source=_src(v["source"]),
                observed_at=v["when"],
                result=v["outcome"],
                subjects=tuple(v.get("subjects") or ()),
            )
            for v in doc.get("verification_history", [])
        ]
        conflicts = [
            Conflict(
                conflict_id=d["id"],
                proposition_ids=tuple(d["about"]),
                status="open" if d["open"] else "resolved",
                note=d.get("note", ""),
            )
            for d in doc.get("disputes", [])
        ]
        lineage = [
            LineageEdge(from_id=e["from"], to_id=e["to"], kind=e["rel"])
            for e in doc.get("source_graph", [])
        ]
        return EvidenceView(
            view_id=view_id or meta.get("view_id", "json"),
            proposition_id=proposition_id,
            assertions=assertions,
            evidence=evidence,
            lineage=lineage,
            conflicts=conflicts,
            checks=checks,
            omitted_sources=omitted_sources if omitted_sources is not None else meta.get("omitted_sources", []),
            retrieval_scope=meta.get("retrieval_scope", "complete") if retrieval_scope is None else retrieval_scope,
            degraded=meta.get("degraded", False) if degraded is None else degraded,
            freshness_policy_seconds=(
                freshness_policy_seconds
                if freshness_policy_seconds is not None
                else meta.get("freshness_policy_seconds", 86400 * 30)
            ),
            subjects=tuple(meta.get("subjects") or ()),
        )
