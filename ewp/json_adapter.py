"""Directory-of-JSON evidence store.

Deliberately does *not* mirror the SQLite schema. Propositions nest
observations, verification_history, and a source_graph. The adapter's
only job is to flatten that into EvidenceView.

Same snapshot contract as SQLite: each (proposition_id, view_id) is an
immutable document; `get_view(pid)` returns the latest. Directory and file
names are hashes of the ids, so no id can collide with another or escape
the store root. Every document records its own ids and is checked on read.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .classify import validate_view
from .codec import canonical_dict, record_identity_conflicts
from .sqlite_adapter import ImmutableRecordError, MissingViewError
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


def _key(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:32]


class JsonFileAdapter:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _pdir(self, proposition_id: str) -> Path:
        return self.root / "propositions" / _key(proposition_id)

    def load_view(self, view: EvidenceView) -> None:
        """Persist using a nested document shape, not SQLite tables."""
        validate_view(view)
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
                    "about": a.proposition_id,
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
                    "about": e.proposition_id,
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
                {"id": c.conflict_id, "about": list(c.proposition_ids), "state": c.status, "note": c.note}
                for c in view.conflicts
            ],
            "source_graph": [
                {"from": e.from_id, "to": e.to_id, "rel": e.kind} for e in view.lineage
            ],
        }
        body = json.dumps(doc, indent=2, sort_keys=True)
        pdir = self._pdir(view.proposition_id)
        path = pdir / "views" / f"{_key(view.view_id)}.json"
        if path.exists():
            # Same content in a different record order is the same snapshot.
            if canonical_dict(self.get_view(view.proposition_id, view.view_id)) != canonical_dict(view):
                raise ImmutableRecordError(
                    f"view {view.view_id!r} of {view.proposition_id!r} is an immutable snapshot with different content"
                )
            return
        stored = [self.get_view(view.proposition_id, vid) for vid in self.view_ids(view.proposition_id)]
        clashes = record_identity_conflicts(stored, view)
        if clashes:
            raise ImmutableRecordError(
                f"{view.proposition_id!r}: ids already name different records in earlier snapshots: {', '.join(clashes)}"
            )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8", newline="\n")
        latest = pdir / "latest.json"
        history = json.loads(latest.read_text(encoding="utf-8"))["view_ids"] if latest.exists() else []
        latest.write_text(json.dumps({"claim": view.proposition_id, "view_ids": history + [view.view_id]}), encoding="utf-8")

    def view_ids(self, proposition_id: str) -> list[str]:
        latest = self._pdir(proposition_id) / "latest.json"
        if not latest.exists():
            return []
        return list(json.loads(latest.read_text(encoding="utf-8"))["view_ids"])

    def get_view(
        self,
        proposition_id: str,
        view_id: str | None = None,
        *,
        omitted_sources: list[str] | None = None,
        retrieval_scope: str | None = None,
        degraded: bool | None = None,
        freshness_policy_seconds: int | None = None,
    ) -> EvidenceView:
        pdir = self._pdir(proposition_id)
        if view_id is None:
            latest = pdir / "latest.json"
            if not latest.exists():
                raise MissingViewError(f"no stored view for {proposition_id!r}")
            view_id = json.loads(latest.read_text(encoding="utf-8"))["view_ids"][-1]
        path = pdir / "views" / f"{_key(view_id)}.json"
        if not path.exists():
            raise MissingViewError(f"no stored view for {proposition_id!r} with view_id {view_id!r}")
        doc = json.loads(path.read_text(encoding="utf-8"))
        meta = doc["view_meta"]
        if doc["claim"] != proposition_id or meta["view_id"] != view_id:
            raise ValueError(f"store corruption: {path} holds {doc['claim']!r}/{meta['view_id']!r}")
        assertions: list[Assertion] = []
        evidence: list[EvidenceItem] = []
        for obs in doc.get("observations", []):
            source = _src(obs["source"])
            if obs["kind"] == "assertion":
                assertions.append(
                    Assertion(
                        assertion_id=obs["id"],
                        proposition_id=obs["about"],
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
                        proposition_id=obs["about"],
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
                subjects=tuple(v["subjects"]),
            )
            for v in doc.get("verification_history", [])
        ]
        conflicts = [
            Conflict(conflict_id=d["id"], proposition_ids=tuple(d["about"]), status=d["state"], note=d.get("note", ""))
            for d in doc.get("disputes", [])
        ]
        lineage = [
            LineageEdge(from_id=e["from"], to_id=e["to"], kind=e["rel"])
            for e in doc.get("source_graph", [])
        ]
        view = EvidenceView(
            view_id=view_id,
            proposition_id=proposition_id,
            assertions=assertions,
            evidence=evidence,
            lineage=lineage,
            conflicts=conflicts,
            checks=checks,
            omitted_sources=meta["omitted_sources"] if omitted_sources is None else omitted_sources,
            retrieval_scope=meta["retrieval_scope"] if retrieval_scope is None else retrieval_scope,
            degraded=meta["degraded"] if degraded is None else degraded,
            freshness_policy_seconds=(
                meta["freshness_policy_seconds"] if freshness_policy_seconds is None else freshness_policy_seconds
            ),
            subjects=tuple(meta["subjects"]),
        )
        validate_view(view)
        return view
