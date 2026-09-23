"""Graphiti → EvidenceView adapter.

Hard boundary: raw graph in, EvidenceView out. Graphiti conclusions stay
store-local metadata. warrant_now() is the only acceptance function.
"""

from __future__ import annotations

from .codec import subjects_from
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


def _source(ep: FakeEpisode) -> SourceRef:
    """One SourceRef per episode. Its time is the episode's own, not the time of
    whichever edge cites it, so every record citing the episode agrees."""
    lid, _basis = lineage_of(ep)
    origin = str(ep.metadata.get("origin_type") or "episode")
    locator = str(ep.metadata.get("origin_locator") or f"graphiti:episode:{ep.uuid}")
    digest = str(ep.metadata.get("content_hash") or f"episode:{ep.uuid}")
    extractor = ep.metadata["extractor_id"] if "extractor_id" in ep.metadata else "graphiti.extract"
    parent = ep.metadata.get("parent_source_id")
    snapshot = str(ep.metadata.get("snapshot_id") or ep.uuid)
    return SourceRef(
        source_id=ep.uuid,
        lineage_id=lid,
        origin_type=origin,
        origin_locator=locator,
        snapshot_id=snapshot,
        content_hash=digest,
        observed_at=ep.reference_time or ep.created_at,
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
                source = _source(ep)
                _lid, basis = lineage_of(ep)
                lineage_basis[source.source_id] = basis
                if "assertion" in edge.roles:
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
                if "evidence" not in edge.roles:
                    continue
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
                        polarity="opposes" if getattr(edge, "polarity", "supports") == "opposes" else "supports",
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

    def _find_parked(self, proposition_id: str):
        """Parked sidecar is identified by kind/content/name, not by Graphiti's UUID.

        Live `add_episode` assigns its own uuid. Looking up only `meta:{pid}`
        is ADAPTER_MAP_LOSS against a real client.
        """
        exact = self.store.episodes.get(f"meta:{proposition_id}")
        if exact is not None:
            return exact
        for ep in self.store.episodes.values():
            meta = ep.metadata or {}
            inner = meta.get("ewp") if isinstance(meta.get("ewp"), dict) else meta
            kind = str(inner.get("kind") or "")
            pid = inner.get("proposition_id")
            content = (ep.content or "").strip()
            if kind == "ewp_parked" and pid == proposition_id:
                return ep
            if content == f"ewp-parked:{proposition_id}":
                return ep
            if content == "ewp-parked" and pid == proposition_id:
                return ep
            if ep.uuid == f"meta:{proposition_id}":
                return ep
        return None

    def _apply_parked(self, view: EvidenceView, proposition_id: str) -> EvidenceView:
        parked = self._find_parked(proposition_id)
        if parked is None:
            return view
        meta = parked.metadata
        if isinstance(meta.get("ewp"), dict):
            meta = meta["ewp"]
        fields = tuple(SourceRef.__dataclass_fields__)
        view.checks = [
            VerificationCheck(
                check_id=c["check_id"],
                method=c["method"],
                scope=c["scope"],
                source=SourceRef(**{k: c["source"][k] for k in fields if k in c["source"]}),
                observed_at=c["observed_at"],
                result=c["result"],
                subjects=subjects_from(c.get("subjects")),
            )
            for c in meta.get("checks", [])
        ]
        view.conflicts = [
            Conflict(c["conflict_id"], tuple(c["proposition_ids"]), c["status"], c.get("note", ""))
            for c in meta.get("conflicts", [])
        ]
        view.lineage = [LineageEdge(e["from"], e["to"], e["kind"]) for e in meta.get("lineage", [])]
        view.omitted_sources = list(meta.get("omitted_sources", view.omitted_sources))
        view.degraded = view.degraded or meta.get("degraded") is True
        if view.retrieval_scope == "complete":
            view.retrieval_scope = meta.get("retrieval_scope", view.retrieval_scope)
        view.freshness_policy_seconds = int(
            meta.get("freshness_policy_seconds", view.freshness_policy_seconds)
        )
        view.subjects = subjects_from(meta.get("subjects"))
        if meta.get("view_id") and view.view_id is None:
            view.view_id = str(meta["view_id"])
        return view

    def raw_view(self, proposition_id: str, fact_text: str | None = None, view_id: str | None = None) -> EvidenceView:
        """All edges for the proposition. view_id defaults to the one parked at ingest."""
        edges = self.store.raw_group(proposition_id)
        if not edges and fact_text:
            edges = self.store.raw_edges(fact_text)
        view = self._edges_to_view(proposition_id, view_id, edges, retrieval_scope="complete")  # type: ignore[arg-type]
        view = self._apply_parked(view, proposition_id)
        if view.view_id is None:
            view.view_id = "graphiti-raw"
        return view

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
