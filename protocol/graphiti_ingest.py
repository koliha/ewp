"""Canonical EvidenceView → Graphiti-shaped records.

Live Graphiti would call add_episode / add_triplet here.
Until graphiti-core is wired, this is the ingest contract the fake store
and the future client must both honor:

* one episode per SourceRef.source_id
* lineage_id goes in episode.metadata, never inferred by Graphiti
* checks and conflicts are *not* EntityEdges; they ride in episode metadata
  so Graphiti invalidation cannot eat them
* EntityEdge.invalid_at is never set from warrant currency
"""

from __future__ import annotations

from .graphiti_records import FakeEntityEdge, FakeEpisode, FakeGraphitiStore
from .types import EvidenceView


def ingest_view(store: FakeGraphitiStore, view: EvidenceView) -> dict:
    """Write evidence only. Returns an ingest report for the four-stage runner."""
    report = {
        "assertions": 0,
        "episodes": 0,
        "checks_parked": 0,
        "conflicts_parked": 0,
        "invalid_at_written": False,
    }
    seen_ep: set[str] = set()

    def put_source(source, content: str) -> None:
        if source.source_id in seen_ep:
            return
        seen_ep.add(source.source_id)
        store.add_episode(
            FakeEpisode(
                uuid=source.source_id,
                content=content,
                created_at=source.observed_at,
                reference_time=source.observed_at,
                metadata={
                    "lineage_id": source.lineage_id,
                    "origin_type": source.origin_type,
                    "origin_locator": source.origin_locator,
                    "content_hash": source.content_hash,
                    "parent_source_id": source.parent_source_id,
                },
            )
        )
        report["episodes"] += 1

    by_text: dict[str, list[str]] = {}
    for a in view.assertions:
        put_source(a.source, a.text)
        by_text.setdefault(a.text, []).append(a.source.source_id)
        report["assertions"] += 1
    for e in view.evidence:
        put_source(e.source, e.content)

    for text, ep_ids in by_text.items():
        store.add_edge(
            FakeEntityEdge(
                uuid=f"edge:{view.proposition_id}:{text[:24]}",
                fact=text,
                group_id=view.proposition_id,
                episodes=list(dict.fromkeys(ep_ids)),
                reference_time=view.assertions[0].asserted_at if view.assertions else None,
                # never copy warrant into Graphiti temporal fields
                valid_at=None,
                invalid_at=None,
                expired_at=None,
            )
        )

    # Park non-edge epistemic objects where Graphiti cannot adjudicate them.
    store.add_episode(
        FakeEpisode(
            uuid=f"meta:{view.proposition_id}",
            content="warrantmem-parked",
            created_at="1970-01-01T00:00:00+00:00",
            metadata={
                "checks": [c.__dict__ | {"source": c.source.__dict__} for c in view.checks],
                "conflicts": [
                    {"conflict_id": c.conflict_id, "proposition_ids": list(c.proposition_ids), "status": c.status, "note": c.note}
                    for c in view.conflicts
                ],
                "lineage": [{"from": e.from_id, "to": e.to_id, "kind": e.kind} for e in view.lineage],
                "omitted_sources": view.omitted_sources,
                "degraded": view.degraded,
                "retrieval_scope": view.retrieval_scope,
                "freshness_policy_seconds": view.freshness_policy_seconds,
            },
        )
    )
    report["checks_parked"] = len(view.checks)
    report["conflicts_parked"] = len(view.conflicts)
    return report
