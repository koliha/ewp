"""Live Graphiti → EvidenceView adapter.

Wraps a real `graphiti_core.Graphiti` client (or a duck-typed stand-in).
The existing `GraphitiAdapter` stays the fake-store conformance kernel.
This module is the production mapping:

    Graphiti EntityEdge + EpisodicNode  →  Fake* records  →  EvidenceView
                                                       →  warrant_now()

Rules (v0.1.0, not negotiable):
* `valid_at` / `invalid_at` / `expired_at` are store-local notes, never warrant.
* Graphiti search that drops edges must set `degraded=True`.
* `origin_type` defaults to `episode` (untrusted). EXTERNAL/HUMAN checks
  only appear if EWP parked them with a trusted origin.
* Lineage is read from episode metadata / source_description / attributes.
  Graphiti must not invent lineage_id.
"""

from __future__ import annotations

import json
from typing import Any, Iterable

from .graphiti_adapter import GraphitiAdapter
from .graphiti_ingest import ingest_view as ingest_into_fake
from .graphiti_records import FakeEntityEdge, FakeEpisode, FakeGraphitiStore
from .live_util import EWP_META_KEY, as_list, attr, ewp_blob, iso, unwrap_collection
from .types import EvidenceView


def _dt(value: Any) -> str | None:
    if value is None or value == "":
        return None
    return iso(value)


def _is_parked_blob(blob: dict[str, Any]) -> bool:
    return str(blob.get("kind") or "") == "ewp_parked"


def episode_from_live(ep: Any) -> FakeEpisode:
    blob = ewp_blob(ep)
    uuid = str(attr(ep, "uuid", "id", default=""))
    created = iso(attr(ep, "created_at", "valid_at", "reference_time", default=None))
    metadata = dict(attr(ep, "metadata", default={}) or {})
    name = str(attr(ep, "name", default="") or "")
    if blob:
        metadata.update(blob)
        metadata.setdefault("lineage_id", blob.get("lineage_id"))
    if name.startswith("meta:") and "proposition_id" not in metadata:
        metadata["proposition_id"] = name.split(":", 1)[1]
        metadata.setdefault("kind", "ewp_parked")
    content = str(attr(ep, "content", default="") or "")
    if not content:
        content = name
    return FakeEpisode(
        uuid=uuid or name or "unknown-episode",
        content=content,
        created_at=created,
        reference_time=_dt(attr(ep, "valid_at", "reference_time", default=None)),
        metadata=metadata,
    )


def edge_from_live(edge: Any) -> FakeEntityEdge:
    blob = ewp_blob(edge)
    episodes = [str(x) for x in as_list(attr(edge, "episodes", default=[]))]
    group = str(attr(edge, "group_id", default=blob.get("proposition_id") or ""))
    return FakeEntityEdge(
        uuid=str(attr(edge, "uuid", "id", default="")),
        fact=str(attr(edge, "fact", "name", default="") or ""),
        group_id=group,
        episodes=episodes,
        valid_at=_dt(attr(edge, "valid_at", default=None)),
        invalid_at=_dt(attr(edge, "invalid_at", default=None)),
        expired_at=_dt(attr(edge, "expired_at", default=None)),
        created_at=_dt(attr(edge, "created_at", default=None)),
        reference_time=_dt(attr(edge, "reference_time", default=None)),
    )


def store_from_live(
    edges: Iterable[Any],
    episodes: Iterable[Any] | None = None,
) -> FakeGraphitiStore:
    store = FakeGraphitiStore()
    for ep in episodes or []:
        fe = episode_from_live(ep)
        store.add_episode(fe)
        blob = fe.metadata
        pid = blob.get("proposition_id")
        parked = _is_parked_blob(blob) or str(fe.content).startswith("ewp-parked")
        if parked and pid:
            alias = f"meta:{pid}"
            if alias != fe.uuid:
                store.add_episode(
                    FakeEpisode(
                        uuid=alias,
                        content=fe.content if str(fe.content).startswith("ewp-parked") else "ewp-parked",
                        created_at=fe.created_at,
                        reference_time=fe.reference_time,
                        metadata=dict(fe.metadata),
                    )
                )
    for edge in edges:
        fe = edge_from_live(edge)
        store.add_edge(fe)
        for epid in fe.episodes:
            if epid not in store.episodes:
                blob = ewp_blob(edge)
                store.add_episode(
                    FakeEpisode(
                        uuid=epid,
                        content=fe.fact,
                        created_at=fe.created_at or iso(None),
                        reference_time=fe.reference_time,
                        metadata={
                            "lineage_id": blob.get("lineage_id", epid),
                            "origin_type": blob.get("origin_type", "episode"),
                            "origin_locator": blob.get("origin_locator", f"graphiti:episode:{epid}"),
                            "content_hash": blob.get("content_hash", f"episode:{epid}"),
                            "parent_source_id": blob.get("parent_source_id"),
                        },
                    )
                )
    return store


class GraphitiClientAdapter:
    """Production adapter. `client` is `graphiti_core.Graphiti` or a test double.

    Expected client surface (all optional except search *or* edge listing):
      * `client.driver` — passed to graphiti_core classmethods
      * `await client.search(query, group_ids=..., num_results=...)`
      * `await client.add_episode(name=..., episode_body=..., ...)`
      * `client.edges.entity.get_by_group_ids(group_ids)`
      * `client.nodes.episodic.get_by_uuid(uuid)` / `get_by_uuids`
    """

    def __init__(
        self,
        client: Any,
        *,
        group_id: str,
        proposition_id: str | None = None,
    ) -> None:
        self.client = client
        self.group_id = group_id
        self.proposition_id = proposition_id or group_id

    async def _list_edges(self) -> list[Any]:
        edges_ns = attr(attr(self.client, "edges", default=None), "entity", default=None)
        if edges_ns is not None and hasattr(edges_ns, "get_by_group_ids"):
            try:
                return list(await edges_ns.get_by_group_ids([self.group_id]) or [])
            except Exception:
                pass
        if hasattr(self.client, "get_edges"):
            return list(await self.client.get_edges(self.group_id) or [])
        EntityEdge = _try_entity_edge()
        if EntityEdge is not None and getattr(self.client, "driver", None) is not None:
            try:
                return list(await EntityEdge.get_by_group_ids(self.client.driver, [self.group_id]) or [])
            except Exception:
                return []
        return []

    async def _list_episodes(self) -> list[Any]:
        """Every episodic node in the group. Parked meta is one of them.

        Must not assume its uuid is `meta:{proposition_id}`.
        """
        if hasattr(self.client, "get_episodes_by_group"):
            try:
                return list(await self.client.get_episodes_by_group(self.group_id) or [])
            except Exception:
                pass
        nodes_ns = attr(attr(self.client, "nodes", default=None), "episodic", default=None)
        if nodes_ns is not None and hasattr(nodes_ns, "get_by_group_ids"):
            try:
                return list(await nodes_ns.get_by_group_ids([self.group_id]) or [])
            except Exception:
                pass
        return []

    async def _get_episodes(self, uuids: list[str]) -> list[Any]:
        listed = await self._list_episodes()
        if listed:
            have = {str(attr(e, "uuid", "id", default="")) for e in listed}
            missing = [u for u in uuids if u not in have]
            if not missing:
                return listed
            extra = await self._get_episodes_by_id(missing)
            return listed + extra
        return await self._get_episodes_by_id(uuids)

    async def _get_episodes_by_id(self, uuids: list[str]) -> list[Any]:
        if not uuids:
            return []
        nodes_ns = attr(attr(self.client, "nodes", default=None), "episodic", default=None)
        if nodes_ns is not None and hasattr(nodes_ns, "get_by_uuids"):
            try:
                return list(await nodes_ns.get_by_uuids(uuids) or [])
            except Exception:
                pass
        if hasattr(self.client, "get_episodes"):
            return list(await self.client.get_episodes(uuids) or [])
        EpisodicNode = _try_episodic_node()
        out: list[Any] = []
        if EpisodicNode is not None and getattr(self.client, "driver", None) is not None:
            for uid in uuids:
                try:
                    out.append(await EpisodicNode.get_by_uuid(self.client.driver, uid))
                except Exception:
                    continue
        return out

    async def _search_edges(self, query: str, limit: int = 20) -> list[Any]:
        if not hasattr(self.client, "search"):
            return []
        raw = await self.client.search(query, group_ids=[self.group_id], num_results=limit)
        return list(unwrap_collection(raw))

    def _view(
        self,
        store: FakeGraphitiStore,
        *,
        view_id: str,
        fact_text: str | None,
        raw_count: int | None,
        retrieval_scope: str,
        hits: list[FakeEntityEdge] | None = None,
    ) -> EvidenceView:
        adapter = GraphitiAdapter(store)
        if hits is not None:
            view = adapter._edges_to_view(
                self.proposition_id,
                view_id,
                hits,
                raw_count=raw_count,
                retrieval_scope=retrieval_scope,
            )
        else:
            view = adapter.raw_view(self.proposition_id, fact_text=fact_text, view_id=view_id)
        return view

    async def raw_view(
        self,
        proposition_id: str | None = None,
        fact_text: str | None = None,
        view_id: str = "graphiti-live-raw",
    ) -> EvidenceView:
        if proposition_id:
            self.proposition_id = proposition_id
        live_edges = await self._list_edges()
        episode_ids: list[str] = []
        for edge in live_edges:
            episode_ids.extend(str(x) for x in as_list(attr(edge, "episodes", default=[])))
        episode_ids.append(f"meta:{self.proposition_id}")
        live_eps = await self._get_episodes(list(dict.fromkeys(episode_ids)))
        store = store_from_live(live_edges, live_eps)
        return self._view(
            store,
            view_id=view_id,
            fact_text=fact_text,
            raw_count=None,
            retrieval_scope="complete",
        )

    async def search_view(
        self,
        query: str,
        proposition_id: str | None = None,
        fact_text: str | None = None,
        view_id: str = "graphiti-live-search",
        limit: int = 20,
    ) -> EvidenceView:
        if proposition_id:
            self.proposition_id = proposition_id
        hits_live = await self._search_edges(query, limit=limit)
        raw_live = await self._list_edges()
        episode_ids: list[str] = []
        for edge in list(hits_live) + list(raw_live):
            episode_ids.extend(str(x) for x in as_list(attr(edge, "episodes", default=[])))
        episode_ids.append(f"meta:{self.proposition_id}")
        live_eps = await self._get_episodes(list(dict.fromkeys(episode_ids)))
        store = store_from_live(raw_live, live_eps)
        hit_ids = {str(attr(h, "uuid", "id", default="")) for h in hits_live}
        hits = [e for e in store.edges.values() if e.uuid in hit_ids]
        if not hits:
            # search returned edges not in group listing — still map them
            extra = store_from_live(hits_live, live_eps)
            hits = list(extra.edges.values())
            for ep in extra.episodes.values():
                store.add_episode(ep)
            for edge in extra.edges.values():
                store.add_edge(edge)
        store.search_hits[query] = [e.uuid for e in hits]
        return self._view(
            store,
            view_id=view_id,
            fact_text=fact_text,
            raw_count=len(store.raw_group(self.proposition_id) or store.raw_edges(fact_text)),
            retrieval_scope="graphiti.search",
            hits=hits,
        )

    async def ingest_view_via_episodes(self, view: EvidenceView) -> dict[str, Any]:
        """Write through Graphiti.add_episode. LLM extraction may drop fields.

        Park EWP checks/conflicts in `source_description` JSON so a later
        read can recover them even if Graphiti ignores attributes.
        Returns an ingest report. Treat text rewrites as INGEST_LOSS.
        """
        if not hasattr(self.client, "add_episode"):
            raise RuntimeError("client has no add_episode")
        report = {"episodes": 0, "checks_parked": 0, "conflicts_parked": 0, "path": "add_episode"}
        seen: set[str] = set()
        for assertion in view.assertions:
            src = assertion.source
            if src.source_id in seen:
                continue
            seen.add(src.source_id)
            payload = {
                EWP_META_KEY: {
                    "lineage_id": src.lineage_id,
                    "origin_type": src.origin_type,
                    "origin_locator": src.origin_locator,
                    "content_hash": src.content_hash,
                    "parent_source_id": src.parent_source_id,
                    "proposition_id": view.proposition_id,
                    "extractor_id": src.extractor_id,
                    "kind": "assertion",
                }
            }
            kwargs = {
                "name": src.source_id,
                "episode_body": assertion.text,
                "source": "text",
                "source_description": json.dumps(payload),
                "reference_time": None,
                "group_id": self.group_id,
            }
            try:
                await self.client.add_episode(**kwargs)
            except TypeError:
                kwargs.pop("reference_time", None)
                await self.client.add_episode(**kwargs)
            report["episodes"] += 1

        park = {
            EWP_META_KEY: {
                "kind": "ewp_parked",
                "stable_name": f"meta:{view.proposition_id}",
                "proposition_id": view.proposition_id,
                "checks": [
                    {**c.__dict__, "source": c.source.__dict__} for c in view.checks
                ],
                "conflicts": [
                    {
                        "conflict_id": c.conflict_id,
                        "proposition_ids": list(c.proposition_ids),
                        "status": c.status,
                        "note": c.note,
                    }
                    for c in view.conflicts
                ],
                "lineage": [
                    {"from": e.from_id, "to": e.to_id, "kind": e.kind} for e in view.lineage
                ],
                "omitted_sources": view.omitted_sources,
                "degraded": view.degraded,
                "retrieval_scope": view.retrieval_scope,
                "freshness_policy_seconds": view.freshness_policy_seconds,
            }
        }
        parked = await self.client.add_episode(
            name=f"meta:{view.proposition_id}",
            episode_body="ewp-parked",
            source="text",
            source_description=json.dumps(park),
            group_id=self.group_id,
        )
        parked_uuid = str(
            attr(attr(parked, "episode", default=parked), "uuid", "id", default="") or ""
        )
        report["checks_parked"] = len(view.checks)
        report["conflicts_parked"] = len(view.conflicts)
        report["parked_name"] = f"meta:{view.proposition_id}"
        report["parked_uuid"] = parked_uuid or None
        return report


def ingest_view_locally(view: EvidenceView) -> FakeGraphitiStore:
    """Deterministic ingest used by tests and as the lossless reference path."""
    store = FakeGraphitiStore()
    ingest_into_fake(store, view)
    return store


def _try_entity_edge() -> Any:
    try:
        from graphiti_core.edges import EntityEdge  # type: ignore

        return EntityEdge
    except Exception:
        return None


def _try_episodic_node() -> Any:
    try:
        from graphiti_core.nodes import EpisodicNode  # type: ignore

        return EpisodicNode
    except Exception:
        return None
