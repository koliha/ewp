"""Graphiti → EvidenceView adapter.

Hard boundary: raw graph in, EvidenceView out. Graphiti conclusions stay
store-local metadata. warrant_now() is the only acceptance function.
"""

from __future__ import annotations

import dataclasses

from .classify import InvalidEvidenceView, parse_ts
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


def unloaded(store: FakeGraphitiStore, episode_id: str) -> bool:
    """An episode the edge cites but the store could not produce. Its role,
    polarity, time, and provenance are unknown."""
    ep = store.episodes.get(episode_id)
    return ep is None or bool(ep.metadata.get("ewp_unloaded"))


def _not_before(record_time: str | None, episode_time: str) -> str:
    """When a record was observed, never earlier than its episode.

    - The record states no time (None): the episode's time.
    - The record's own time does not parse (or is empty): kept as is, so the
      record is unavailable at every T, as the kernel reads it.
    - The episode's time is unknown: the record's time (nothing to compare).
    - Otherwise the later of the two: an edge cannot backdate its episode.
    """
    if record_time is None:
        return episode_time
    try:
        record = parse_ts(record_time)
    except (ValueError, TypeError):
        return record_time
    try:
        episode = parse_ts(episode_time)
    except (ValueError, TypeError):
        return record_time
    return record_time if record >= episode else episode_time


def _declared_time(ep: FakeEpisode, role_time: str, fallback: str) -> str:
    """The record time EWP ingest wrote on the episode for this role
    (`asserted_at` or `observed_at`), exactly as written; otherwise the
    fallback (an edge from Graphiti's own extractor declares none)."""
    meta = ep.metadata.get("ewp") if isinstance(ep.metadata.get("ewp"), dict) else ep.metadata
    value = meta.get(role_time)
    return fallback if value is None else value


_EPISODE_ROLES = {"assertion": ("assertion",), "evidence": ("evidence",), "both": ("assertion", "evidence")}


def _episode_roles(ep: FakeEpisode, edge: FakeEntityEdge) -> tuple[tuple[str, ...], str]:
    """Which records this episode carries on this edge, and its polarity. EWP
    live ingest writes `kind` and `polarity` on each episode; an edge Graphiti
    extracted from several episodes cannot hold them per episode, so the
    episode's own declaration wins and the edge's values are the fallback."""
    meta = ep.metadata.get("ewp") if isinstance(ep.metadata.get("ewp"), dict) else ep.metadata
    roles = _EPISODE_ROLES.get(str(meta.get("kind") or ""), edge.roles)
    declared = meta.get("polarity")
    polarity = declared if declared in ("supports", "opposes") else getattr(edge, "polarity", "supports")
    return roles, ("opposes" if polarity == "opposes" else "supports")


def declared_proposition(store: FakeGraphitiStore, episode_id: str) -> str | None:
    """The proposition an episode declares (EWP ingest writes `proposition_id`
    into each episode's metadata), or None."""
    ep = store.episodes.get(episode_id)
    if ep is None:
        return None
    meta = ep.metadata.get("ewp") if isinstance(ep.metadata.get("ewp"), dict) else ep.metadata
    return str(meta["proposition_id"]) if meta.get("proposition_id") else None


def episodes_for(store: FakeGraphitiStore, edge: FakeEntityEdge, proposition_id: str, *, undeclared: bool) -> list[str]:
    """The episodes of an edge that are about this proposition. Graphiti merges
    one fact cited by several episodes into one edge, so an edge can carry
    episodes of different propositions; each proposition keeps its own.
    `undeclared` says whether an episode declaring nothing counts."""
    keep = []
    for epid in edge.episodes:
        declared = declared_proposition(store, epid)
        if (declared is None and undeclared) or (declared is not None and _about(declared, proposition_id)):
            keep.append(epid)
    return keep


def _about(declared: str, proposition_id: str) -> bool:
    return declared == proposition_id or declared.startswith(proposition_id + ":")


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
            episode_ids = edge.episodes or [edge.uuid]
            for i, epid in enumerate(episode_ids):
                if unloaded(self.store, epid):
                    # Unknown role and polarity (it may oppose): never guessed
                    # into a record, always reported as missing.
                    omitted.append(f"graphiti:episode:{epid}")
                    continue
                ep = self.store.episodes[epid]
                source = _source(ep)
                # When the record was observed: never earlier than its episode
                # (the source's observation). An edge's reference time can make
                # it later, never earlier. `valid_at` is when the fact held in
                # the world (store-local context, kept in the note), not when
                # anyone observed it, so it never makes a record available.
                fallback = _not_before(edge.reference_time, source.observed_at)
                roles, polarity = _episode_roles(ep, edge)
                asserted_at = _declared_time(ep, "asserted_at", fallback)
                observed_at = _declared_time(ep, "observed_at", fallback)
                _lid, basis = lineage_of(ep)
                lineage_basis[source.source_id] = basis
                if "assertion" in roles:
                    assertions.append(
                        Assertion(
                            assertion_id=f"{edge.uuid}:a:{i}",
                            proposition_id=proposition_id,
                            text=edge.fact,
                            asserted_by="graphiti.extract",
                            assertion_confidence=0.5,
                            source=source,
                            asserted_at=asserted_at,
                        )
                    )
                if "evidence" not in roles:
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
                        polarity=polarity,
                        source=source,
                        content=note,
                        observed_at=observed_at,
                    )
                )

        degraded = False
        scope = retrieval_scope
        if raw_count is not None and raw_count > len(edges):
            degraded = True
            scope = "graphiti.search"
            fact = edges[0].fact if edges else None
            omitted += [e.uuid for e in self.store.raw_edges(fact) if e not in edges]

        return EvidenceView(
            view_id=view_id,
            proposition_id=proposition_id,
            assertions=assertions,
            evidence=evidence,
            retrieval_scope=scope,
            degraded=degraded,
            omitted_sources=sorted(set(omitted)),
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
        # The parked list is what the ingested view omitted; what this read
        # could not load is added to it, never replaced by it.
        parked_omitted = meta.get("omitted_sources")
        if parked_omitted is None:
            parked_omitted = []
        if not isinstance(parked_omitted, list):
            raise InvalidEvidenceView(f"parked omitted_sources={parked_omitted!r} must be a list of strings")
        view.omitted_sources = sorted(set(parked_omitted) | set(view.omitted_sources))
        # A parked `degraded` that is not a boolean is not read as False:
        # it is carried into the view, where validation refuses it.
        parked_degraded = meta.get("degraded", False)
        view.degraded = True if (view.degraded or parked_degraded is True) else parked_degraded
        if view.retrieval_scope == "complete":
            view.retrieval_scope = meta.get("retrieval_scope", view.retrieval_scope)
        # Carried as written, never coerced (int(True) would be 1 second).
        view.freshness_policy_seconds = meta.get("freshness_policy_seconds", view.freshness_policy_seconds)
        view.subjects = subjects_from(meta.get("subjects"))
        if meta.get("view_id") and view.view_id is None:
            view.view_id = str(meta["view_id"])
        return view

    def raw_view(self, proposition_id: str, fact_text: str | None = None, view_id: str | None = None) -> EvidenceView:
        """All edges for the proposition. view_id defaults to the one parked at ingest."""
        edges = self.store.raw_group(proposition_id)
        scope = "complete"
        if not edges and fact_text:
            # A text match is similarity, not identity: never complete, and an
            # episode that declares another proposition stays out.
            edges = []
            for e in self.store.raw_edges(fact_text):
                keep = episodes_for(self.store, e, proposition_id, undeclared=True)
                if keep:
                    edges.append(dataclasses.replace(e, episodes=keep))
            scope = "graphiti.fact_text"
        view = self._edges_to_view(proposition_id, view_id, edges, retrieval_scope=scope)  # type: ignore[arg-type]
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
