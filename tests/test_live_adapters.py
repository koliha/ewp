#!/usr/bin/env python3
"""Mapping tests for live Graphiti and Mem0 adapters. No third-party stores."""

from __future__ import annotations

import asyncio
import dataclasses
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ewp.fixtures import EVAL, fixture_verified_current
from ewp.graphiti_client_adapter import (
    GraphitiClientAdapter,
    edge_from_live,
    episode_from_live,
    store_from_live,
)
from ewp.mem0_adapter import Mem0Adapter, items_to_view, source_from_mem0
from ewp.types import Policy
from ewp.warrant import warrant_now


class FakeGraphitiClient:
    def __init__(self) -> None:
        self.edges_data: list[SimpleNamespace] = []
        self.episodes_data: dict[str, SimpleNamespace] = {}
        self.added: list[dict] = []

    async def get_edges(self, group_id: str):
        return [e for e in self.edges_data if e.group_id == group_id]

    async def get_episodes(self, uuids: list[str]):
        return [self.episodes_data[u] for u in uuids if u in self.episodes_data]

    async def search(self, query: str, group_ids=None, num_results=10):
        hits = [e for e in self.edges_data if query.lower() in e.fact.lower()]
        return hits[:num_results]

    async def add_episode(self, name, episode_body, source="text", source_description="", group_id=None, **kw):
        # Graphiti assigns its own uuid. The episode *name* is not the uuid.
        uid = f"g-{len(self.added) + 1}"
        rec = {
            "name": name,
            "episode_body": episode_body,
            "source_description": source_description,
            "group_id": group_id,
            "uuid": uid,
        }
        self.added.append(rec)
        self.episodes_data[uid] = SimpleNamespace(
            uuid=uid,
            name=name,
            content=episode_body,
            created_at="2026-09-21T18:31:00+00:00",
            source_description=source_description,
            metadata={},
            group_id=group_id,
        )
        return SimpleNamespace(episode=SimpleNamespace(uuid=uid, content=episode_body, name=name))

    async def get_episodes_by_group(self, group_id: str):
        return [e for e in self.episodes_data.values() if getattr(e, "group_id", None) == group_id]


ENTITY_PARAMS = {"user_id", "agent_id", "run_id"}


def _entity_filters(filters, kwargs, method):
    """The mem0ai 2.x read contract (checked against mem0/memory/main.py and
    mem0/client/main.py): entity ids only in filters, at least one required."""
    if ENTITY_PARAMS & set(kwargs):
        raise ValueError(f"Top-level entity parameters are not supported in {method}(). Use filters=...")
    if not filters or not any(k in filters for k in ENTITY_PARAMS):
        raise ValueError("filters must contain at least one of: user_id, agent_id, run_id")
    return filters


class FakeMem0:
    """Mirrors OSS `mem0.Memory` 2.x: keyword-only reads, entity ids in
    `filters`, `get_all` bounded by `top_k` (default 20) with no paging."""

    def __init__(self) -> None:
        self.rows: list[dict] = []

    def add(self, messages, *, user_id=None, agent_id=None, run_id=None, metadata=None, infer=True, **kw):
        text = messages[0]["content"] if messages else ""
        row = {
            "id": f"m{len(self.rows)+1}",
            "memory": text,
            "hash": f"h{len(self.rows)+1}",
            "metadata": metadata or {},
            "created_at": "2026-09-21T18:31:00+00:00",
            "user_id": user_id,
            "agent_id": agent_id,
            "run_id": run_id,
            "score": None,
        }
        self.rows.append(row)
        return {"results": [{"id": row["id"], "memory": text, "event": "ADD"}]}

    def _scoped(self, filters):
        return [r for r in self.rows if all(r.get(k) == v for k, v in filters.items() if k in ENTITY_PARAMS)]

    def get_all(self, *, filters=None, top_k=20, show_expired=False, **kwargs):
        filters = _entity_filters(filters, kwargs, "get_all")
        return {"results": [dict(r) for r in self._scoped(filters)][:top_k]}

    def search(self, query, *, top_k=20, filters=None, threshold=0.1, rerank=False, **kwargs):
        filters = _entity_filters(filters, kwargs, "search")
        hits = [r for r in self._scoped(filters) if query.lower() in r["memory"].lower()]
        return {"results": [dict(r, score=0.91) for r in hits[:top_k]]}


class FakeMem0Hosted(FakeMem0):
    """Mirrors hosted `mem0.MemoryClient` 2.x get_all: (options=None, **kwargs),
    paginated {"count", "next", "previous", "results"}."""

    def get_all(self, options=None, **kwargs):
        filters = _entity_filters(kwargs.pop("filters", None), kwargs, "get_all")
        page, size = int(kwargs.get("page", 1)), int(kwargs.get("page_size", 100))
        rows = [dict(r) for r in self._scoped(filters)]
        chunk = rows[(page - 1) * size: page * size]
        more = page * size < len(rows)
        return {"count": len(rows), "next": f"?page={page + 1}" if more else None, "previous": None, "results": chunk}


class GraphitiMappingTests(unittest.TestCase):
    def test_edge_and_episode_mapping_preserves_lineage(self):
        ep = SimpleNamespace(
            uuid="ep-1",
            content="nmap said 22/tcp open",
            created_at="2026-09-21T18:31:00+00:00",
            valid_at="2026-09-21T18:31:00+00:00",
            metadata={"lineage_id": "lin-tool", "origin_type": "tool"},
        )
        edge = SimpleNamespace(
            uuid="edge-1",
            fact="server01 exposes ssh",
            group_id="prop-ssh",
            episodes=["ep-1"],
            valid_at="2026-01-01T00:00:00+00:00",
            invalid_at="2026-09-01T00:00:00+00:00",
            expired_at=None,
            created_at="2026-09-21T18:31:00+00:00",
            reference_time="2026-09-21T18:31:00+00:00",
            attributes={},
        )
        fake_ep = episode_from_live(ep)
        fake_edge = edge_from_live(edge)
        self.assertEqual(fake_ep.metadata["lineage_id"], "lin-tool")
        self.assertEqual(fake_edge.invalid_at, "2026-09-01T00:00:00+00:00")
        store = store_from_live([edge], [ep])
        self.assertEqual(store.episodes["ep-1"].metadata["origin_type"], "tool")

    def test_live_raw_view_round_trip(self):
        client = FakeGraphitiClient()
        client.episodes_data["ep-1"] = SimpleNamespace(
            uuid="ep-1",
            content="tool observation",
            created_at="2026-09-21T18:31:00+00:00",
            metadata={"lineage_id": "L1", "origin_type": "tool"},
        )
        client.edges_data.append(
            SimpleNamespace(
                uuid="e1",
                fact="server01 runs Windows Server 2022",
                group_id="p-os",
                episodes=["ep-1"],
                valid_at=None,
                invalid_at=None,
                expired_at=None,
                created_at="2026-09-21T18:31:00+00:00",
                reference_time="2026-09-21T18:31:00+00:00",
            )
        )
        adapter = GraphitiClientAdapter(client, group_id="p-os")
        view = asyncio.run(adapter.raw_view("p-os"))
        self.assertEqual(len(view.assertions), 1)
        self.assertEqual(view.assertions[0].source.lineage_id, "L1")
        self.assertEqual(view.assertions[0].source.origin_type, "tool")
        self.assertFalse(view.degraded)
        self.assertEqual(len(view.evidence), 1)
        self.assertNotIn("graphiti.valid_at", view.evidence[0].content)  # no valid_at, no note

    def _shared_group_client(self):
        """One Graphiti group (a user) holding two propositions and an edge
        that declares none."""
        client = FakeGraphitiClient()
        for epid, pid in (("ep-p1", "P1"), ("ep-p2", "P2"), ("ep-none", None)):
            meta = {"lineage_id": f"L-{epid}", "origin_type": "tool"}
            if pid:
                meta["proposition_id"] = pid
            client.episodes_data[epid] = SimpleNamespace(
                uuid=epid, content=epid, created_at="2026-09-21T18:31:00+00:00",
                valid_at="2026-09-21T18:31:00+00:00", metadata=meta)
        for uid, epid, fact in (("e-p1", "ep-p1", "server01 runs Windows"), ("e-p2", "ep-p2", "server02 runs Linux"),
                                ("e-none", "ep-none", "server03 runs BSD")):
            client.edges_data.append(SimpleNamespace(
                uuid=uid, fact=fact, group_id="user-42", episodes=[epid], valid_at=None, invalid_at=None,
                expired_at=None, created_at="2026-09-21T18:31:00+00:00"))
        return client

    def test_shared_group_selects_by_declared_proposition(self):
        client = self._shared_group_client()
        view = asyncio.run(GraphitiClientAdapter(client, group_id="user-42", proposition_id="P1").raw_view())
        self.assertEqual([a.text for a in view.assertions], ["server01 runs Windows"])
        self.assertEqual(view.retrieval_scope, "complete")
        other = asyncio.run(GraphitiClientAdapter(client, group_id="user-42", proposition_id="P2").raw_view())
        self.assertEqual([a.text for a in other.assertions], ["server02 runs Linux"])
        # Search over the shared group returns both propositions' edges; only P1's enter P1's view.
        found = asyncio.run(GraphitiClientAdapter(client, group_id="user-42", proposition_id="P1").search_view("runs"))
        self.assertEqual([a.text for a in found.assertions], ["server01 runs Windows"])

    def test_edge_merged_from_two_propositions_appears_in_each(self):
        """Graphiti merges one fact cited by several episodes into one edge."""
        client = FakeGraphitiClient()
        for epid, pid in (("ep-1", "P1"), ("ep-2", "P2")):
            client.episodes_data[epid] = SimpleNamespace(
                uuid=epid, content=epid, created_at="2026-09-21T18:31:00+00:00",
                valid_at="2026-09-21T18:31:00+00:00",
                metadata={"lineage_id": f"L-{epid}", "origin_type": "tool", "proposition_id": pid})
        client.edges_data.append(SimpleNamespace(
            uuid="e-shared", fact="the build is broken", group_id="user-42", episodes=["ep-1", "ep-2"],
            valid_at=None, invalid_at=None, expired_at=None, created_at="2026-09-21T18:31:00+00:00"))
        for pid, epid in (("P1", "ep-1"), ("P2", "ep-2")):
            view = asyncio.run(GraphitiClientAdapter(client, group_id="user-42", proposition_id=pid).raw_view())
            self.assertEqual([a.source.source_id for a in view.assertions], [epid], pid)
            found = asyncio.run(GraphitiClientAdapter(client, group_id="user-42", proposition_id=pid).search_view("build"))
            self.assertEqual([a.source.source_id for a in found.assertions], [epid], pid)

    def test_episode_polarity_and_roles_survive_an_extracted_edge(self):
        """Graphiti's extractor makes one edge from an assertion episode and an
        opposing-evidence episode; the edge carries neither role nor polarity."""
        client = FakeGraphitiClient()
        declared = {
            "ep-claim": {"kind": "assertion"},
            "ep-camera": {"kind": "evidence", "polarity": "opposes"},
        }
        for epid, extra in declared.items():
            client.episodes_data[epid] = SimpleNamespace(
                uuid=epid, content=epid, created_at="2026-09-21T18:31:00+00:00", valid_at="2026-09-21T18:31:00+00:00",
                metadata={"ewp": {"lineage_id": f"L-{epid}", "origin_type": "tool", "proposition_id": "P1", **extra}})
        client.edges_data.append(SimpleNamespace(
            uuid="e-x", fact="the door is locked", group_id="user-42", episodes=["ep-claim", "ep-camera"],
            valid_at=None, invalid_at=None, expired_at=None, created_at="2026-09-21T18:31:00+00:00"))
        view = asyncio.run(GraphitiClientAdapter(client, group_id="user-42", proposition_id="P1").raw_view())
        self.assertEqual([a.source.source_id for a in view.assertions], ["ep-claim"])
        self.assertEqual([(e.source.source_id, e.polarity) for e in view.evidence], [("ep-camera", "opposes")])

    def test_live_ingest_declares_every_role_and_refuses_mixed_polarity(self):
        client = FakeGraphitiClient()
        base = fixture_verified_current()
        asyncio.run(GraphitiClientAdapter(client, group_id="user-42", proposition_id="P-win").ingest_view_via_episodes(base))
        import json as _json
        blobs = {e.name: _json.loads(e.source_description)["ewp"] for e in client.episodes_data.values()
                 if not str(getattr(e, "name", "")).startswith("meta:")}
        shared = {a.source.source_id for a in base.assertions} & {e.source.source_id for e in base.evidence}
        self.assertTrue(shared, "fixture must have a source that is both assertion and evidence")
        for sid in shared:
            self.assertEqual(blobs[sid]["kind"], "both", sid)
            self.assertEqual(blobs[sid]["polarity"], "supports", sid)
        mixed = dataclasses.replace(base, evidence=base.evidence + [dataclasses.replace(
            base.evidence[0], evidence_id="e-opp", polarity="opposes", content="not so")])
        with self.assertRaises(ValueError):
            asyncio.run(GraphitiClientAdapter(FakeGraphitiClient(), group_id="g", proposition_id="P-win").ingest_view_via_episodes(mixed))

    def test_unloadable_episode_in_shared_group_degrades_the_view(self):
        client = self._shared_group_client()
        client.edges_data.append(SimpleNamespace(
            uuid="e-gone", fact="server01 was reimaged", group_id="user-42", episodes=["ep-gone"],
            valid_at=None, invalid_at=None, expired_at=None, created_at="2026-09-21T18:31:00+00:00"))
        view = asyncio.run(GraphitiClientAdapter(client, group_id="user-42", proposition_id="P1").raw_view())
        self.assertIn("graphiti:episode:ep-gone", view.omitted_sources)
        self.assertEqual(warrant_now(view, Policy(), "2026-09-22T00:00:00+00:00").warrant.sufficiency, "DEGRADED")
        found = asyncio.run(GraphitiClientAdapter(client, group_id="user-42", proposition_id="P1").search_view("server01"))
        self.assertIn("graphiti:episode:ep-gone", found.omitted_sources)

    def test_unloadable_episode_in_proposition_group_is_omitted_not_supporting(self):
        """group_id == proposition_id: a missing episode used to become supporting evidence."""
        client = FakeGraphitiClient()
        client.episodes_data["ep-ok"] = SimpleNamespace(
            uuid="ep-ok", content="tool saw it", created_at="2026-09-21T18:31:00+00:00",
            valid_at="2026-09-21T18:31:00+00:00", metadata={"lineage_id": "L-ok", "origin_type": "tool"})
        client.edges_data.append(SimpleNamespace(
            uuid="e1", fact="server01 runs Windows Server 2022", group_id="p-os", episodes=["ep-ok", "ep-gone"],
            valid_at=None, invalid_at=None, expired_at=None, created_at="2026-09-21T18:31:00+00:00"))
        view = asyncio.run(GraphitiClientAdapter(client, group_id="p-os").raw_view("p-os"))
        self.assertEqual({a.source.source_id for a in view.assertions} | {e.source.source_id for e in view.evidence}, {"ep-ok"})
        self.assertIn("graphiti:episode:ep-gone", view.omitted_sources)
        self.assertEqual(warrant_now(view, Policy(), "2026-09-22T00:00:00+00:00").warrant.sufficiency, "DEGRADED")

    def test_fake_store_missing_episode_is_omitted(self):
        from ewp.graphiti_adapter import GraphitiAdapter
        from ewp.graphiti_records import FakeEntityEdge, FakeGraphitiStore

        store = FakeGraphitiStore()
        store.add_edge(FakeEntityEdge("e1", "a fact", "P1", ["ep-missing"]))
        view = GraphitiAdapter(store).raw_view("P1")
        self.assertEqual((view.assertions, view.evidence), ([], []))
        self.assertEqual(view.omitted_sources, ["graphiti:episode:ep-missing"])

    def test_search_keeps_unloaded_episodes_when_hits_add_edges(self):
        """Search returns an edge the group listing did not; the second scoping
        pass must not drop the first pass's unloaded episodes."""
        client = self._shared_group_client()
        client.edges_data.append(SimpleNamespace(
            uuid="e-gone", fact="server01 was reimaged", group_id="user-42", episodes=["ep-gone"],
            valid_at=None, invalid_at=None, expired_at=None, created_at="2026-09-21T18:31:00+00:00"))
        extra = SimpleNamespace(
            uuid="e-unlisted", fact="server01 runs Windows too", group_id="user-42", episodes=["ep-p1"],
            valid_at=None, invalid_at=None, expired_at=None, created_at="2026-09-21T18:31:00+00:00")
        real_search = client.search

        async def search(query, group_ids=None, num_results=10):
            return list(await real_search(query, group_ids=group_ids, num_results=num_results)) + [extra]

        client.search = search
        adapter = GraphitiClientAdapter(client, group_id="user-42", proposition_id="P1")
        raw = asyncio.run(adapter.raw_view())
        found = asyncio.run(adapter.search_view("server01"))
        self.assertIn("graphiti:episode:ep-gone", raw.omitted_sources)
        self.assertIn("graphiti:episode:ep-gone", found.omitted_sources)
        self.assertIn("server01 runs Windows too", [a.text for a in found.assertions])

    def test_search_never_crosses_the_group_boundary(self):
        """A client whose search ignores group_ids must not leak another user's facts."""
        client = self._shared_group_client()
        client.episodes_data["ep-private"] = SimpleNamespace(
            uuid="ep-private", content="private", created_at="2026-09-21T18:31:00+00:00",
            valid_at="2026-09-21T18:31:00+00:00",
            metadata={"lineage_id": "L-private", "origin_type": "tool", "proposition_id": "P1"})
        client.edges_data.append(SimpleNamespace(
            uuid="e-private", fact="server01 belongs to another user", group_id="other-user", episodes=["ep-private"],
            valid_at=None, invalid_at=None, expired_at=None, created_at="2026-09-21T18:31:00+00:00"))
        leaky_list = client.get_edges

        async def get_edges(group_id):  # a listing that ignores its filter, too
            return list(client.edges_data)

        client.get_edges = get_edges
        adapter = GraphitiClientAdapter(client, group_id="user-42", proposition_id="P1")
        found = asyncio.run(adapter.search_view("server01"))
        raw = asyncio.run(adapter.raw_view())
        for view in (found, raw):
            self.assertNotIn("server01 belongs to another user", [a.text for a in view.assertions])
            self.assertNotIn("ep-private", {a.source.source_id for a in view.assertions})
        client.get_edges = leaky_list

    def test_edge_reference_time_never_backdates_its_episode(self):
        client = FakeGraphitiClient()
        client.episodes_data["ep-late"] = SimpleNamespace(
            uuid="ep-late", content="seen on the 24th", created_at="2026-09-24T09:00:00+00:00",
            valid_at="2026-09-24T09:00:00+00:00", metadata={"lineage_id": "L", "origin_type": "tool"})
        client.edges_data.append(SimpleNamespace(
            uuid="e-back", fact="server01 was patched", group_id="p-patch", episodes=["ep-late"], valid_at=None,
            invalid_at=None, expired_at=None, created_at="2026-09-24T09:00:00+00:00",
            reference_time="2026-09-20T00:00:00+00:00"))
        view = asyncio.run(GraphitiClientAdapter(client, group_id="p-patch").raw_view())
        self.assertEqual({e.observed_at for e in view.evidence} | {a.asserted_at for a in view.assertions},
                         {"2026-09-24T09:00:00+00:00"})

    def test_parked_completeness_fields_are_not_coerced(self):
        from ewp.classify import InvalidEvidenceView
        from ewp.graphiti_adapter import GraphitiAdapter
        from ewp.graphiti_ingest import ingest_view as ingest_fake
        from ewp.graphiti_records import FakeGraphitiStore

        for field, bad in (("degraded", "true"), ("degraded", 1), ("freshness_policy_seconds", True),
                           ("freshness_policy_seconds", "86400"), ("omitted_sources", "possible-contradictor")):
            store = FakeGraphitiStore()
            ingest_fake(store, fixture_verified_current())
            store.episodes["meta:P-win"].metadata[field] = bad
            with self.assertRaises(InvalidEvidenceView, msg=f"{field}={bad!r}"):
                warrant_now(GraphitiAdapter(store).raw_view("P-win"), Policy(), EVAL)

    def test_episodes_from_another_group_are_not_read(self):
        client = self._shared_group_client()
        client.episodes_data["ep-p1"].group_id = "other-user"  # the cited episode now belongs elsewhere
        client.episodes_data["meta-other"] = SimpleNamespace(
            uuid="meta-other", name="meta:P1", content="ewp-parked", group_id="other-user",
            created_at="2026-09-21T18:31:00+00:00", valid_at=None,
            metadata={"ewp": {"kind": "ewp_parked", "proposition_id": "P1", "checks": [], "conflicts": [],
                              "lineage": [], "omitted_sources": [], "degraded": False, "subjects": ["x"]}})

        async def by_group(group_id):
            return list(client.episodes_data.values())  # a listing that ignores its filter

        client.get_episodes_by_group = by_group
        view = asyncio.run(GraphitiClientAdapter(client, group_id="user-42", proposition_id="P1").raw_view())
        self.assertEqual(view.subjects, ())
        self.assertIn("graphiti:episode:ep-p1", view.omitted_sources)
        self.assertEqual(view.assertions, [])

    def test_record_times_ride_on_the_episode(self):
        """An assertion made after its source was observed keeps its own time
        (it used to take the first assertion's time, or the episode's)."""
        from ewp.graphiti_adapter import GraphitiAdapter
        from ewp.graphiti_ingest import ingest_view as ingest_fake
        from ewp.graphiti_records import FakeGraphitiStore

        base = fixture_verified_current()
        late = dataclasses.replace(base.assertions[0], asserted_at="2026-09-21T20:00:00+00:00")
        view = dataclasses.replace(base, assertions=[late])
        store = FakeGraphitiStore()
        ingest_fake(store, view)
        back = GraphitiAdapter(store).raw_view(view.proposition_id)
        self.assertEqual({a.asserted_at for a in back.assertions}, {"2026-09-21T20:00:00+00:00"})
        before = warrant_now(back, Policy(), "2026-09-21T19:00:00+00:00").warrant
        self.assertEqual(before, warrant_now(view, Policy(), "2026-09-21T19:00:00+00:00").warrant)
        mixed = dataclasses.replace(base, assertions=[late, dataclasses.replace(
            late, assertion_id="a2", text="other", asserted_at="2026-09-21T20:30:00+00:00")])
        with self.assertRaises(ValueError):
            ingest_fake(FakeGraphitiStore(), mixed)
        with self.assertRaises(ValueError):
            asyncio.run(GraphitiClientAdapter(FakeGraphitiClient(), group_id="g", proposition_id="P-win").ingest_view_via_episodes(mixed))

    def test_newest_parked_sidecar_applies_whatever_the_listing_order(self):
        """Live Graphiti keeps every parked sidecar; the newest must win even
        when the listing returns an older one last."""
        from ewp.sqlite_adapter import LedgerError
        from ewp.types import Conflict

        base = fixture_verified_current()
        v2 = dataclasses.replace(base, view_id="v2", conflicts=[Conflict("c1", ("P-win",), "open", "")])

        def client_with_both(reverse: bool, same_instant: bool = False):
            client = FakeGraphitiClient()
            adapter = GraphitiClientAdapter(client, group_id="P-win", proposition_id="P-win")
            asyncio.run(adapter.ingest_view_via_episodes(base))
            asyncio.run(adapter.ingest_view_via_episodes(v2))
            items = list(client.episodes_data.items())
            for i, (_k, ep) in enumerate(items):
                ep.group_id = "P-win"
                ep.created_at = "2026-09-21T10:00:00+00:00" if same_instant else f"2026-09-21T10:{i:02d}:00+00:00"
            if reverse:
                client.episodes_data = dict(reversed(items))
            sources = [k for k, ep in items if not str(getattr(ep, "name", "")).startswith("meta:")]
            client.edges_data.append(SimpleNamespace(
                uuid="e1", fact="server01 runs Windows Server 2022", group_id="P-win", episodes=sources,
                valid_at=None, invalid_at=None, expired_at=None, created_at="2026-09-21T10:00:00+00:00"))
            return adapter

        for reverse in (False, True):
            view = asyncio.run(client_with_both(reverse).raw_view("P-win"))
            self.assertEqual([c.status for c in view.conflicts], ["open"], f"reverse={reverse}")
        with self.assertRaises(LedgerError):
            asyncio.run(client_with_both(False, same_instant=True).raw_view("P-win"))

    def test_episode_without_any_time_is_not_available(self):
        """A store record of unknown time is unavailable at every T (it used to
        read as 1970, available at every T)."""
        client = FakeGraphitiClient()
        client.episodes_data["ep-t"] = SimpleNamespace(
            uuid="ep-t", content="no time", metadata={"lineage_id": "L", "origin_type": "tool"})
        client.edges_data.append(SimpleNamespace(
            uuid="e-t", fact="server01 is up", group_id="p-t", episodes=["ep-t"],
            valid_at=None, invalid_at=None, expired_at=None, created_at=None))
        view = asyncio.run(GraphitiClientAdapter(client, group_id="p-t").raw_view())
        w = warrant_now(view, Policy(), "2026-09-22T00:00:00+00:00").warrant
        self.assertEqual((w.acceptance, w.sufficiency), ("UNACCEPTED", "INSUFFICIENT"))

    def test_fact_text_fallback_is_degraded_and_respects_declared_identity(self):
        from ewp.graphiti_adapter import GraphitiAdapter
        from ewp.graphiti_records import FakeEntityEdge, FakeEpisode, FakeGraphitiStore

        store = FakeGraphitiStore()
        store.add_episode(FakeEpisode("ep-a", "x", "2026-09-20T00:00:00+00:00", metadata={"proposition_id": "P-A"}))
        store.add_episode(FakeEpisode("ep-u", "x", "2026-09-20T00:00:00+00:00", metadata={}))
        store.add_edge(FakeEntityEdge("e-a", "shared fact", "g", ["ep-a"]))
        view = GraphitiAdapter(store).raw_view("P-B", fact_text="shared fact")
        self.assertEqual(view.assertions, [], "an edge declared for P-A must not join P-B")
        store.add_edge(FakeEntityEdge("e-u", "shared fact", "g", ["ep-u"]))
        view = GraphitiAdapter(store).raw_view("P-B", fact_text="shared fact")
        self.assertEqual(len(view.assertions), 1)
        self.assertEqual(view.retrieval_scope, "graphiti.fact_text")
        self.assertEqual(warrant_now(view, Policy(), "2026-09-21T00:00:00+00:00").warrant.sufficiency, "DEGRADED")

    def test_valid_at_never_makes_a_record_available_early(self):
        """valid_at is when the fact held in the world, not when it was observed."""
        client = FakeGraphitiClient()
        client.episodes_data["ep-late"] = SimpleNamespace(
            uuid="ep-late", content="observed on the 24th", created_at="2026-09-24T09:00:00+00:00",
            valid_at="2026-09-24T09:00:00+00:00", metadata={"lineage_id": "L", "origin_type": "tool"})
        client.edges_data.append(SimpleNamespace(
            uuid="e-late", fact="server01 was patched", group_id="p-patch", episodes=["ep-late"],
            valid_at="2026-09-20T00:00:00+00:00", invalid_at=None, expired_at=None,
            created_at="2026-09-24T09:00:00+00:00"))
        view = asyncio.run(GraphitiClientAdapter(client, group_id="p-patch").raw_view())
        self.assertEqual({e.observed_at for e in view.evidence}, {"2026-09-24T09:00:00+00:00"})
        early = warrant_now(view, Policy(), "2026-09-21T00:00:00+00:00").warrant
        self.assertEqual((early.acceptance, early.sufficiency), ("UNACCEPTED", "INSUFFICIENT"))
        self.assertIn("graphiti.valid_at=2026-09-20", view.evidence[0].content)

    def test_search_marks_degraded_when_edges_dropped(self):
        client = FakeGraphitiClient()
        for i, fact in enumerate(["alpha fact", "beta fact"], start=1):
            client.edges_data.append(
                SimpleNamespace(
                    uuid=f"e{i}",
                    fact=fact,
                    group_id="p",
                    episodes=[f"ep{i}"],
                    valid_at=None,
                    invalid_at=None,
                    expired_at=None,
                    created_at="2026-09-21T18:31:00+00:00",
                    reference_time=None,
                )
            )
            client.episodes_data[f"ep{i}"] = SimpleNamespace(
                uuid=f"ep{i}",
                content=fact,
                created_at="2026-09-21T18:31:00+00:00",
                metadata={"lineage_id": f"L{i}"},
            )
        adapter = GraphitiClientAdapter(client, group_id="p", proposition_id="p")
        view = asyncio.run(adapter.search_view("alpha", proposition_id="p"))
        self.assertTrue(view.degraded)
        self.assertEqual(view.retrieval_scope, "graphiti.search")
        self.assertEqual(len(view.assertions), 1)

    def test_ingest_via_episodes_parks_metadata(self):
        client = FakeGraphitiClient()
        adapter = GraphitiClientAdapter(client, group_id="p")
        view = fixture_verified_current()
        report = asyncio.run(adapter.ingest_view_via_episodes(view))
        self.assertGreater(report["episodes"], 0)
        self.assertTrue(any(a["name"].startswith("meta:") for a in client.added))
        self.assertTrue(any("ewp" in a["source_description"] for a in client.added))
        self.assertTrue(report["parked_uuid"])
        self.assertFalse(report["parked_uuid"].startswith("meta:"))

    def test_parked_checks_survive_graphiti_assigned_uuid(self):
        client = FakeGraphitiClient()
        adapter = GraphitiClientAdapter(client, group_id="P-win", proposition_id="P-win")
        src_view = fixture_verified_current()
        asyncio.run(adapter.ingest_view_via_episodes(src_view))
        parked = [e for e in client.episodes_data.values() if str(getattr(e, "content", "")).startswith("ewp-parked")]
        self.assertEqual(len(parked), 1)
        self.assertNotEqual(parked[0].uuid, f"meta:{src_view.proposition_id}")
        out = asyncio.run(adapter.raw_view(src_view.proposition_id))
        self.assertEqual(len(out.checks), len(src_view.checks))
        self.assertEqual(out.checks[0].method, src_view.checks[0].method)
        self.assertEqual(out.checks[0].result, src_view.checks[0].result)


class Mem0MappingTests(unittest.TestCase):
    def test_reads_use_the_2x_contract(self):
        """Entity ids in filters; the OSS fake rejects top-level user_id like mem0ai 2.x."""
        client = FakeMem0()
        with self.assertRaises(ValueError):
            client.get_all(user_id="u1")
        adapter = Mem0Adapter(client, user_id="u1", infer=False)
        adapter.ingest_view(fixture_verified_current())
        self.assertEqual(adapter.raw_view("P-win").view_id, fixture_verified_current().view_id)
        self.assertTrue(adapter.search_view("P-win", "Windows").assertions)

    def test_oss_read_at_the_limit_is_refused(self):
        from ewp.sqlite_adapter import LedgerError

        adapter = Mem0Adapter(FakeMem0(), user_id="u1", infer=False, read_limit=2)
        Mem0Adapter(adapter.client, user_id="u1", infer=False).ingest_view(fixture_verified_current())
        with self.assertRaises(LedgerError):
            adapter.raw_view("P-win")

    def _two_snapshots(self):
        base = fixture_verified_current()
        adapter = Mem0Adapter(FakeMem0(), user_id="u1", infer=False)
        adapter.ingest_view(base)
        v2 = dataclasses.replace(base, view_id="v2", evidence=base.evidence + [dataclasses.replace(
            base.evidence[0], evidence_id="e-opp", polarity="opposes", content="server01 runs Windows Server 2019")])
        adapter.ingest_view(v2)
        return adapter, base, v2

    def test_lost_newest_sidecar_does_not_serve_an_older_snapshot_as_latest(self):
        from ewp.codec import canonical_dict
        from ewp.sqlite_adapter import LedgerError

        adapter, base, _v2 = self._two_snapshots()
        adapter.client.rows = [r for r in adapter.client.rows
                               if not (r["metadata"]["ewp"].get("kind") == "ewp_parked" and r["metadata"]["ewp"].get("view_id") == "v2")]
        with self.assertRaises(LedgerError):
            adapter.raw_view("P-win")
        with self.assertRaises(LedgerError):
            adapter.search_view("P-win", "Windows")
        self.assertEqual(canonical_dict(adapter.raw_view("P-win", base.view_id)), canonical_dict(base))

    def test_interrupted_newer_ingest_blocks_latest_until_retried(self):
        from ewp.codec import canonical_dict
        from ewp.sqlite_adapter import LedgerError

        adapter, _base, v2 = self._two_snapshots()
        v3 = dataclasses.replace(v2, view_id="v3", degraded=True)
        real_add = adapter._add
        calls = []

        def crash_on_sidecar(text, metadata):
            if metadata["ewp"].get("kind") == "ewp_parked":
                raise ConnectionError("lost connection before the sidecar")
            calls.append(text)
            return real_add(text, metadata)

        adapter._add = crash_on_sidecar
        with self.assertRaises(ConnectionError):
            adapter.ingest_view(v3)
        adapter._add = real_add
        with self.assertRaises(LedgerError):
            adapter.raw_view("P-win")
        self.assertEqual(canonical_dict(adapter.raw_view("P-win", "v2")), canonical_dict(v2))
        adapter.ingest_view(v3)  # the retry commits
        self.assertEqual(canonical_dict(adapter.raw_view("P-win")), canonical_dict(v3))

    def test_concurrent_commits_with_one_sequence_have_no_latest(self):
        from ewp.codec import canonical_dict
        from ewp.sqlite_adapter import LedgerError

        adapter, _base, v2 = self._two_snapshots()
        v3a = dataclasses.replace(v2, view_id="v3a", degraded=True)
        v3b = dataclasses.replace(v2, view_id="v3b", evidence=v2.evidence[:1])
        before = adapter._sidecars(adapter._for_proposition(adapter._all_items(), "P-win"))
        adapter.ingest_view(v3a)
        racer = Mem0Adapter(adapter.client, user_id="u1", infer=False)
        racer._sidecars = lambda items: before  # read the store before v3a committed
        racer.ingest_view(v3b)
        with self.assertRaises(LedgerError):
            adapter.raw_view("P-win")
        self.assertEqual(canonical_dict(adapter.raw_view("P-win", "v3a")), canonical_dict(v3a))
        v4 = dataclasses.replace(v2, view_id="v4")
        adapter.ingest_view(v4)
        self.assertEqual(canonical_dict(adapter.raw_view("P-win")), canonical_dict(v4))

    def test_sidecar_without_digest_is_refused(self):
        from ewp.sqlite_adapter import LedgerError

        adapter, _base, _v2 = self._two_snapshots()
        for r in adapter.client.rows:
            if r["metadata"]["ewp"].get("kind") == "ewp_parked" and r["metadata"]["ewp"].get("view_id") == "v2":
                del r["metadata"]["ewp"]["digest"]
        with self.assertRaises(LedgerError):
            adapter.raw_view("P-win")
        for r in adapter.client.rows:
            if r["metadata"]["ewp"].get("kind") == "ewp_parked":
                r["metadata"]["ewp"]["seq"] = "not-a-number"
        with self.assertRaises(LedgerError):
            adapter.raw_view("P-win", "v2")

    def test_sidecar_needs_a_positive_sequence(self):
        from ewp.sqlite_adapter import LedgerError

        for bad in (None, 0, -1, True):
            adapter, _base, _v2 = self._two_snapshots()
            for r in adapter.client.rows:
                blob = r["metadata"]["ewp"]
                if blob.get("kind") == "ewp_parked" and blob.get("view_id") == "v2":
                    if bad is None:
                        del blob["seq"]
                    else:
                        blob["seq"] = bad
            with self.assertRaises(LedgerError, msg=repr(bad)):
                adapter.raw_view("P-win")

    def test_add_is_never_retried(self):
        """A TypeError raised after the client wrote must not trigger a second
        write of the same memory under one ingest_id."""
        client = FakeMem0()
        real_add = client.add

        def add_then_fail(messages, **kw):
            real_add(messages, **kw)
            raise TypeError("client bug after the write")

        client.add = add_then_fail
        with self.assertRaises(TypeError):
            Mem0Adapter(client, user_id="u1", infer=False).ingest_view(fixture_verified_current())
        self.assertEqual(len(client.rows), 1)

    def test_unverified_memory_confidence_is_not_coerced(self):
        from ewp.classify import InvalidEvidenceView

        client = FakeMem0()
        client.add([{"role": "user", "content": "likes rye"}], user_id="u1", metadata={"ewp": {
            "proposition_id": "P-rye", "kind": "assertion", "assertion_confidence": "high"}})
        view = Mem0Adapter(client, user_id="u1", infer=False).raw_view("P-rye")
        with self.assertRaises(InvalidEvidenceView):
            warrant_now(view, Policy(), "2026-09-22T00:00:00+00:00")

    def test_memory_without_any_time_is_not_available(self):
        client = FakeMem0()
        client.add([{"role": "user", "content": "likes rye"}], user_id="u1",
                   metadata={"ewp": {"proposition_id": "P-rye", "kind": "memory"}})
        for row in client.rows:
            row["created_at"] = None
        view = Mem0Adapter(client, user_id="u1", infer=False).raw_view("P-rye")
        w = warrant_now(view, Policy(), "2026-09-22T00:00:00+00:00").warrant
        self.assertEqual(w.acceptance, "UNACCEPTED")

    def test_legacy_check_memory_with_empty_time_is_not_available(self):
        """A per-check memory (kind ewp_check) with an empty observed_at stays
        unavailable; it used to take the memory's ingest time."""
        client = FakeMem0()
        client.add([{"role": "user", "content": "port 22 open"}], user_id="u1", metadata={"ewp": {
            "proposition_id": "P-ssh", "kind": "ewp_check", "check_id": "k1", "method": "tool_observation",
            "result": "supports", "observed_at": "", "origin_type": "tool", "lineage_id": "L"}})
        view = Mem0Adapter(client, user_id="u1", infer=False).raw_view("P-ssh")
        self.assertEqual([c.observed_at for c in view.checks], [""])
        self.assertEqual(warrant_now(view, Policy(), "2026-09-22T00:00:00+00:00").warrant.verification, "NONE")

    def test_hosted_client_pages_through_every_memory(self):
        from ewp.codec import canonical_dict
        from ewp.sqlite_adapter import LedgerError

        client = FakeMem0Hosted()
        adapter = Mem0Adapter(client, user_id="u1", infer=False)
        adapter.page_size = 1  # every memory on its own page
        view = fixture_verified_current()
        adapter.ingest_view(view)
        self.assertEqual(canonical_dict(adapter.raw_view("P-win")), canonical_dict(view))
        real = client.get_all
        client.get_all = lambda options=None, **kw: dict(real(options, **kw), count=99)
        with self.assertRaises(LedgerError):
            adapter.raw_view("P-win")

    def test_source_defaults_to_extract(self):
        item = {"id": "abc", "memory": "likes rye", "created_at": "2026-01-01T00:00:00+00:00"}
        src = source_from_mem0(item, fallback_id="abc")
        self.assertEqual(src.origin_type, "extract")
        self.assertEqual(src.lineage_id, "abc")
        self.assertEqual(src.extractor_id, "mem0.extract")

    def test_metadata_overrides_origin_and_lineage(self):
        item = {
            "id": "abc",
            "memory": "port 22 open",
            "created_at": "2026-09-21T18:31:00+00:00",
            "metadata": {
                "ewp": {
                    "origin_type": "tool",
                    "lineage_id": "scan-1",
                    "kind": "memory",
                    "proposition_id": "ssh",
                }
            },
        }
        src = source_from_mem0(item, fallback_id="abc")
        self.assertEqual(src.origin_type, "tool")
        self.assertEqual(src.lineage_id, "scan-1")

    def test_search_degrades_when_get_all_has_more(self):
        items_all = [
            {"id": "1", "memory": "A", "created_at": "2026-01-01T00:00:00Z", "metadata": {"ewp": {"kind": "memory"}}},
            {"id": "2", "memory": "B", "created_at": "2026-01-01T00:00:00Z", "metadata": {"ewp": {"kind": "memory"}}},
        ]
        view = items_to_view(
            items_all[:1],
            proposition_id="p",
            view_id="s",
            retrieval_scope="mem0.search",
            raw_count=2,
            omitted=["2"],
        )
        self.assertTrue(view.degraded)
        self.assertEqual(view.omitted_sources, ["2"])

    def test_parked_checks_round_trip_through_client(self):
        mem = FakeMem0()
        adapter = Mem0Adapter(mem, user_id="u1", infer=False)
        src_view = fixture_verified_current()
        report = adapter.ingest_view(src_view)
        self.assertGreater(report["memories"], 0)
        self.assertEqual(report["checks_parked"], len(src_view.checks))
        out = adapter.raw_view(src_view.proposition_id)
        self.assertEqual(len(out.checks), len(src_view.checks))
        self.assertEqual(out.checks[0].method, src_view.checks[0].method)
        self.assertEqual(out.checks[0].result, src_view.checks[0].result)
        # warrant must still be computable
        result = warrant_now(out, Policy(), EVAL)
        self.assertEqual(result.warrant.verification, warrant_now(src_view, Policy(), EVAL).warrant.verification)

    def test_untagged_memory_does_not_enter_proposition_view(self):
        mem = FakeMem0()
        adapter = Mem0Adapter(mem, user_id="u1")
        mem.add([{"role": "user", "content": "I like rye bread"}], user_id="u1")
        view = fixture_verified_current()
        adapter.ingest_view(view)
        out = adapter.raw_view(view.proposition_id)
        texts = [a.text for a in out.assertions]
        self.assertTrue(any("Windows" in t for t in texts))
        self.assertFalse(any("rye" in t.lower() for t in texts))
        self.assertEqual(len(adapter.unscoped_items()), 1)
        searched = adapter.search_view(view.proposition_id, query="rye")
        self.assertFalse(any("rye" in a.text.lower() for a in searched.assertions))

    def test_search_keeps_parked_sidecar(self):
        mem = FakeMem0()
        adapter = Mem0Adapter(mem, user_id="u1")
        view = fixture_verified_current()
        adapter.ingest_view(view)
        searched = adapter.search_view(view.proposition_id, query="Windows")
        self.assertGreaterEqual(len(searched.checks), 1)
        # retrieval scores stay in adapter_meta
        self.assertEqual(searched.adapter_meta["store"], "mem0")


if __name__ == "__main__":
    unittest.main()
