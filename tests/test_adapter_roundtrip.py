#!/usr/bin/env python3
"""Store neutrality as a property: every fixture, through every adapter,
yields the same normative axes as the in-memory reference.

A field an adapter forgets to persist (subjects[], completeness, freshness)
shows up here as a WARRANT_MISMATCH instead of waiting for a reviewer.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from protocol.fixtures import EVAL
from protocol.graphiti_adapter import GraphitiAdapter
from protocol.graphiti_client_adapter import GraphitiClientAdapter
from protocol.graphiti_ingest import ingest_view
from protocol.graphiti_records import FakeGraphitiStore
from protocol.json_adapter import JsonFileAdapter
from protocol.laundering import EVAL_AT, PACK as LAUNDER
from protocol.mem0_adapter import Mem0Adapter
from protocol.pathological import PACK as PATHO
from protocol.sqlite_adapter import SQLiteAdapter
from protocol.types import EvidenceView, Policy
from protocol.warrant import warrant_now
from runner import FIXTURES
from test_live_adapters import FakeGraphitiClient, FakeMem0

POLICY = Policy()


def all_fixtures() -> list[tuple[str, EvidenceView, str]]:
    out = [(name, cases[0][1], cases[0][2]) for name, cases in FIXTURES]
    out += [(name, factory(), EVAL) for name, factory in PATHO]
    out += [(name, factory(), EVAL_AT.get(name, EVAL)) for name, factory in LAUNDER]
    return out


def via_sqlite(view: EvidenceView) -> EvidenceView:
    db = SQLiteAdapter()
    db.load_view(view)
    return db.get_view(view.proposition_id, view.view_id)


def via_json(view: EvidenceView) -> EvidenceView:
    with TemporaryDirectory() as tmp:
        store = JsonFileAdapter(tmp)
        store.load_view(view)
        return store.get_view(view.proposition_id, view.view_id)


def via_fake_graphiti(view: EvidenceView) -> EvidenceView:
    store = FakeGraphitiStore()
    ingest_view(store, view)
    fact = view.assertions[0].text if view.assertions else view.proposition_id
    return GraphitiAdapter(store).raw_view(view.proposition_id, fact)


def via_mem0(view: EvidenceView) -> EvidenceView:
    adapter = Mem0Adapter(FakeMem0(), user_id="u1", infer=False)
    adapter.ingest_view(view)
    return adapter.raw_view(view.proposition_id)


ADAPTERS = [
    ("SQLite", via_sqlite),
    ("JSON", via_json),
    ("FakeGraphiti", via_fake_graphiti),
    ("Mem0", via_mem0),
]

# (adapter, fixture) pairs where the store's own data model loses
# information EWP needs. Each entry must name the loss. An entry here is
# a documented ADAPTER_MAP_LOSS, not a pass.
KNOWN_LOSS: dict[tuple[str, str], str] = {}


def axes(view: EvidenceView, evaluated_at: str) -> dict:
    return warrant_now(view, POLICY, evaluated_at).normative()["warrant"]


def test_every_fixture_through_every_adapter() -> None:
    failures: list[str] = []
    for name, view, evaluated_at in all_fixtures():
        expected = axes(view, evaluated_at)
        for label, through in ADAPTERS:
            got = axes(through(view), evaluated_at)
            if got == expected:
                continue
            if (label, name) in KNOWN_LOSS:
                continue
            diff = {k: (expected[k], got[k]) for k in expected if expected[k] != got[k]}
            failures.append(f"{label:13} {name:45} {diff}")
    if failures:
        print("WARRANT_MISMATCH after adapter round trip (expected, got):")
        print("\n".join(failures))
        raise AssertionError(f"{len(failures)} adapter round-trip mismatches")
    print(f"PASS {len(all_fixtures())} fixtures x {len(ADAPTERS)} adapters: normative axes preserved")


def test_live_graphiti_parks_subjects() -> None:
    from protocol.laundering import customer_scope_mismatch

    src = customer_scope_mismatch()
    client = FakeGraphitiClient()
    adapter = GraphitiClientAdapter(client, group_id=src.proposition_id, proposition_id=src.proposition_id)
    asyncio.run(adapter.ingest_view_via_episodes(src))
    out = asyncio.run(adapter.raw_view(src.proposition_id))
    assert out.subjects == src.subjects, out.subjects
    assert [c.subjects for c in out.checks] == [c.subjects for c in src.checks], out.checks
    print("PASS live Graphiti parked sidecar preserves view and check subjects")


def main() -> int:
    test_every_fixture_through_every_adapter()
    test_live_graphiti_parks_subjects()
    print("ADAPTER ROUND-TRIP SUITE PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
