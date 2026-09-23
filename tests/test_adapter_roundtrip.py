#!/usr/bin/env python3
"""Store neutrality, checked two ways for every fixture through every adapter.

1. Axes: the same normative axes as the in-memory reference.
2. Fields: the same EvidenceView. SQLite, JSON, Mem0, and the JSON codec
   must return every SCHEMA.md field unchanged. Graphiti's data model
   cannot hold some fields; those are listed in GRAPHITI_FIELD_LOSSES and
   everything else (text, times, full source provenance, polarity) must
   come back.

A field an adapter forgets to persist shows up here instead of waiting
for a reviewer.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from ewp.codec import view_from_dict
from ewp.fixtures import EVAL
from ewp.graphiti_adapter import GraphitiAdapter
from ewp.graphiti_client_adapter import GraphitiClientAdapter
from ewp.graphiti_ingest import ingest_view
from ewp.graphiti_records import FakeGraphitiStore
from ewp.json_adapter import JsonFileAdapter
from ewp.laundering import EVAL_AT, PACK as LAUNDER
from ewp.mem0_adapter import Mem0Adapter
from ewp.pathological import PACK as PATHO
from ewp.sqlite_adapter import SQLiteAdapter
from ewp.types import EvidenceView, Policy
from ewp.warrant import warrant_now
from runner import FIXTURES
from test_live_adapters import FakeGraphitiClient, FakeMem0

POLICY = Policy()

# Fields Graphiti's edge/episode model cannot represent. Each is named with
# the reason; nothing outside this list may change.
GRAPHITI_FIELD_LOSSES = {
    "assertion_id / evidence_id": "Graphiti assigns its own edge ids",
    "asserted_by / assertion_confidence": "an extracted fact edge has no asserter or confidence",
    "evidence content": "evidence is the episode body plus store-local temporal notes",
    "duplicate assertions": "identical text from one source collapses to one fact edge",
}


def all_fixtures() -> list[tuple[str, EvidenceView, str]]:
    out = [(name, cases[0][1], cases[0][2]) for name, cases in FIXTURES]
    out += [(name, factory(), EVAL) for name, factory in PATHO]
    out += [(name, factory(), EVAL_AT.get(name, EVAL)) for name, factory in LAUNDER]
    return out


def via_codec(view: EvidenceView) -> EvidenceView:
    return view_from_dict(json.loads(json.dumps(view.to_dict())))


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


STRICT_ADAPTERS = [
    ("Codec", via_codec),
    ("SQLite", via_sqlite),
    ("JSON", via_json),
    ("Mem0", via_mem0),
]
ADAPTERS = STRICT_ADAPTERS + [("FakeGraphiti", via_fake_graphiti)]


def axes(view: EvidenceView, evaluated_at: str) -> dict:
    return warrant_now(view, POLICY, evaluated_at).normative()["warrant"]


def canonical(view: EvidenceView) -> dict:
    """Every SCHEMA.md field, order-independent. adapter_meta is adapter-local."""
    d = view.to_dict()
    d.pop("adapter_meta", None)
    for part, key in (("assertions", "assertion_id"), ("evidence", "evidence_id"), ("checks", "check_id"), ("conflicts", "conflict_id")):
        d[part] = sorted(d[part], key=lambda r: str(r[key]))
    d["lineage"] = sorted(d["lineage"], key=lambda e: (e["from_id"], e["to_id"], e["kind"]))
    for c in d["conflicts"]:
        c["proposition_ids"] = sorted(c["proposition_ids"])
    return d


def _source_key(s) -> tuple:
    return (s.source_id, s.lineage_id, s.origin_type, s.origin_locator, s.snapshot_id,
            s.content_hash, s.observed_at, s.extractor_id, s.parent_source_id)


def graphiti_comparable(view: EvidenceView) -> dict:
    """Everything except GRAPHITI_FIELD_LOSSES, keyed by content."""
    return {
        "assertions": {(a.proposition_id, a.text, a.asserted_at) + _source_key(a.source) for a in view.assertions},
        "evidence": {(e.proposition_id, e.polarity, e.observed_at) + _source_key(e.source) for e in view.evidence},
        "checks": canonical(view)["checks"],
        "conflicts": canonical(view)["conflicts"],
        "lineage": canonical(view)["lineage"],
        "meta": (view.view_id, view.omitted_sources, view.retrieval_scope, view.degraded, view.freshness_policy_seconds, tuple(view.subjects)),
    }


def test_every_fixture_through_every_adapter() -> None:
    failures: list[str] = []
    for name, view, evaluated_at in all_fixtures():
        expected = axes(view, evaluated_at)
        for label, through in ADAPTERS:
            got = axes(through(view), evaluated_at)
            if got != expected:
                diff = {k: (expected[k], got[k]) for k in expected if expected[k] != got[k]}
                failures.append(f"{label:13} {name:45} {diff}")
    if failures:
        print("WARRANT_MISMATCH after adapter round trip (expected, got):")
        print("\n".join(failures))
        raise AssertionError(f"{len(failures)} adapter round-trip mismatches")
    print(f"PASS {len(all_fixtures())} fixtures x {len(ADAPTERS)} adapters: normative axes preserved")


def test_every_field_round_trips() -> None:
    failures: list[str] = []
    for name, view, _t in all_fixtures():
        want = canonical(view)
        for label, through in STRICT_ADAPTERS:
            got = canonical(through(view))
            if got != want:
                fields = sorted(k for k in want if want[k] != got.get(k))
                failures.append(f"{label:13} {name:45} fields differ: {fields}")
        if graphiti_comparable(via_fake_graphiti(view)) != graphiti_comparable(view):
            failures.append(f"{'FakeGraphiti':13} {name:45} provenance/metadata differ beyond GRAPHITI_FIELD_LOSSES")
    if failures:
        print("INGEST_LOSS / ADAPTER_MAP_LOSS at field level:")
        print("\n".join(failures))
        raise AssertionError(f"{len(failures)} field-level round-trip losses")
    print(
        f"PASS {len(all_fixtures())} fixtures: every field round-trips through "
        f"{', '.join(label for label, _ in STRICT_ADAPTERS)}; FakeGraphiti loses only {len(GRAPHITI_FIELD_LOSSES)} listed fields"
    )


def test_live_graphiti_parks_subjects() -> None:
    from ewp.laundering import customer_scope_mismatch

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
    test_every_field_round_trips()
    test_live_graphiti_parks_subjects()
    print("ADAPTER ROUND-TRIP SUITE PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
