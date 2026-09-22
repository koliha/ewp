"""Graphiti → EvidenceView adapter.

Hard boundary: raw graph in, EvidenceView out. Graphiti conclusions stay
store-local metadata. warrant_now() is the only acceptance function.
"""

from __future__ import annotations

from .graphiti_records import FakeEpisode, FakeEntityEdge, FakeGraphitiStore
from .types import (
    Assertion,
    Conflict,
    EvidenceItem,
    EvidenceView,
    LineageEdge,
    SourceRef,
    VerificationCheck,
)


def lineage_of(ep: FakeEpisode) -> tuple[str, str]:
    """Return (lineage_id, basis). Basis is adapter metadata, not a warrant axis."""
    lid = ep.metadata.get("lineage_id")
    if lid:
        return str(lid), "explicit"
    return ep.uuid, "fallback_episode_uuid"


def _source(ep: FakeEpisode, observed_at: str) -> SourceRef:
    lid, _basis = lineage_of(ep)
    origin = str(ep.metadata.get("origin_type") or "episode")
    locator = str(ep.metadata.get("origin_locator") or f"graphiti:episode:{ep.uuid}")
    digest = str(ep.metadata.get("content_hash") or f"episode:{ep.uuid}")
    extractor = ep.metadata.get("extractor_id") or "graphiti.extract"
    parent = ep.metadata.get("parent_source_id")
    snapshot = str(ep.metadata.get("snapshot_id") or ep.uuid)
    return SourceRef(
        source_id=ep.uuid,
        lineage_id=lid,
        origin_type=origin,
        origin_locator=locator,
        snapshot_id=snapshot,
        content_hash=digest,
        observed_at=observed_at,
        extractor_id=str(extractor) if extractor else None,
        parent_source_id=str(parent) if parent else None,
    )


def _fallback_episode(uuid: str) -> FakeEpisode:
    return FakeEpisode(uuid=uuid, content="", created_at="1970-01-01T00:00:00+00:00")


class GraphitiAdapter:
    def __init__(self, store: FakeGraphitiStore) -> None:
        self.store = store

    def _edges_to_view(
        self,
        proposition_id: str,
        view_id: str,
        edges: list[FakeEntityEdge],
        *,
        raw_count: int | None = None,
        retrieval_scope: str = "complete",
    ) -> EvidenceView:
        assertions: list[Assertion] = []
        evidence: list[EvidenceItem] = []
        omitted: list[str] = []
        lineage_basis: dict[str, str] = {}

        for edge in edges:
            when = edge.reference_time or edge.valid_at or edge.created_at or "1970-01-01T00:00:00+00:00"
            episode_ids = edge.episodes or [edge.uuid]
            for i, epid in enumerate(episode_ids):
                ep = self.store.episodes.get(epid) or _fallback_episode(epid)
                source = _source(ep, when)
                _lid, basis = lineage_of(ep)
                lineage_basis[source.source_id] = basis
                assertions.append(
                    Assertion(
                        assertion_id=f"{edge.uuid}:a:{i}",
                        proposition_id=proposition_id,
                        text=edge.fact,
                        asserted_by="graphiti.extract",
                        assertion_confidence=0.5,
                        source=source,
                        asserted_at=when,
                    )
                )
                note = ep.content or edge.fact
                if edge.valid_at:
                    note += f" [graphiti.valid_at={edge.valid_at}]"
                if edge.invalid_at:
                    note += f" [graphiti.invalid_at={edge.invalid_at} store-local]"
                if edge.expired_at:
                    note += f" [graphiti.expired_at={edge.expired_at} maintenance]"
                evidence.append(
                    EvidenceItem(
                        evidence_id=f"{edge.uuid}:e:{i}",
                        proposition_id=proposition_id,
                        polarity="supports",
                        source=source,
                        content=note,
                        observed_at=when,
                    )
                )

        degraded = False
        scope = retrieval_scope
        if raw_count is not None and raw_count > len(edges):
            degraded = True
            scope = "graphiti.search"
            fact = edges[0].fact if edges else None
            omitted = [e.uuid for e in self.store.raw_edges(fact) if e not in edges]

        return EvidenceView(
            view_id=view_id,
            proposition_id=proposition_id,
            assertions=assertions,
            evidence=evidence,
            retrieval_scope=scope,
            degraded=degraded,
            omitted_sources=omitted,
            adapter_meta={"lineage_basis": lineage_basis, "store": "graphiti"},
        )

    def _apply_parked(self, view: EvidenceView, proposition_id: str) -> EvidenceView:
        parked = self.store.episodes.get(f"meta:{proposition_id}")
        if parked is None:
            return view
        meta = parked.metadata
        fields = tuple(SourceRef.__dataclass_fields__)
        view.checks = [
            VerificationCheck(
                check_id=c["check_id"],
                method=c["method"],
                scope=c["scope"],
                source=SourceRef(**{k: c["source"][k] for k in fields}),
                observed_at=c["observed_at"],
                result=c["result"],
            )
            for c in meta.get("checks", [])
        ]
        view.conflicts = [
            Conflict(c["conflict_id"], tuple(c["proposition_ids"]), c["status"], c.get("note", ""))
            for c in meta.get("conflicts", [])
        ]
        view.lineage = [LineageEdge(e["from"], e["to"], e["kind"]) for e in meta.get("lineage", [])]
        view.omitted_sources = list(meta.get("omitted_sources", view.omitted_sources))
        view.degraded = view.degraded or bool(meta.get("degraded", False))
        if view.retrieval_scope == "complete":
            view.retrieval_scope = meta.get("retrieval_scope", view.retrieval_scope)
        view.freshness_policy_seconds = int(
            meta.get("freshness_policy_seconds", view.freshness_policy_seconds)
        )
        return view

    def raw_view(self, proposition_id: str, fact_text: str | None = None, view_id: str = "graphiti-raw") -> EvidenceView:
        edges = self.store.raw_group(proposition_id)
        if not edges and fact_text:
            edges = self.store.raw_edges(fact_text)
        view = self._edges_to_view(proposition_id, view_id, edges, retrieval_scope="complete")
        return self._apply_parked(view, proposition_id)

    def search_view(
        self, proposition_id: str, query: str, fact_text: str | None = None, view_id: str = "graphiti-search"
    ) -> EvidenceView:
        hits = self.store.search(query)
        raw = self.store.raw_group(proposition_id) or (self.store.raw_edges(fact_text) if fact_text else [])
        view = self._edges_to_view(
            proposition_id,
            view_id,
            hits,
            raw_count=len(raw),
            retrieval_scope="graphiti.search",
        )
        return self._apply_parked(view, proposition_id)
