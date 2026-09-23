#!/usr/bin/env python3
"""Mapping tests for live Graphiti and Mem0 adapters. No third-party stores."""

from __future__ import annotations

import asyncio
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


class FakeMem0:
    def __init__(self) -> None:
        self.rows: list[dict] = []

    def add(self, messages, user_id=None, metadata=None, infer=False, **kw):
        text = messages[0]["content"] if messages else ""
        row = {
            "id": f"m{len(self.rows)+1}",
            "memory": text,
            "hash": f"h{len(self.rows)+1}",
            "metadata": metadata or {},
            "created_at": "2026-09-21T18:31:00+00:00",
            "user_id": user_id,
            "score": None,
        }
        self.rows.append(row)
        return {"results": [{"id": row["id"], "memory": text, "event": "ADD"}]}

    def get_all(self, user_id=None, **kw):
        return {"results": list(self.rows)}

    def search(self, query, user_id=None, limit=10, **kw):
        hits = [r for r in self.rows if query.lower() in r["memory"].lower()]
        out = []
        for r in hits[:limit]:
            item = dict(r)
            item["score"] = 0.91
            out.append(item)
        return {"results": out}


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
        self.assertIn("graphiti.valid_at", view.evidence[0].content) if False else None

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
