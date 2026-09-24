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

from ewp.codec import canonical_dict, view_from_dict
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
    "record proposition_id": "a record naming a variant pid:<suffix> reads back as the view's proposition",
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
    """Every SCHEMA.md field, order-independent (the codec's canonical form)."""
    return canonical_dict(view)


def _source_key(s) -> tuple:
    return (s.source_id, s.lineage_id, s.origin_type, s.origin_locator, s.snapshot_id,
            s.content_hash, s.observed_at, s.extractor_id, s.parent_source_id)


def graphiti_comparable(view: EvidenceView) -> dict:
    """Everything except GRAPHITI_FIELD_LOSSES, keyed by content."""
    return {
        "assertions": {(a.text, a.asserted_at) + _source_key(a.source) for a in view.assertions},
        "evidence": {(e.polarity, e.observed_at) + _source_key(e.source) for e in view.evidence},
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


def test_mem0_snapshots() -> None:
    import dataclasses

    from ewp.fixtures import fixture_verified_current
    from ewp.sqlite_adapter import ImmutableRecordError, LedgerError, MissingViewError

    mem = Mem0Adapter(FakeMem0(), user_id="u1", infer=False)
    base = fixture_verified_current()
    v1 = dataclasses.replace(base, view_id="v1")
    v2 = dataclasses.replace(base, view_id="v2", degraded=True,
                             evidence=base.evidence + [dataclasses.replace(base.evidence[0], evidence_id="e2")])
    mem.ingest_view(v1)
    mem.ingest_view(v2)
    assert canonical(mem.raw_view("P-win", "v1")) == canonical(v1)
    assert canonical(mem.raw_view("P-win", "v2")) == canonical(v2)
    assert mem.raw_view("P-win").view_id == "v2"
    rows = len(mem.client.rows)
    assert mem.ingest_view(v1)["stored"] is False and len(mem.client.rows) == rows, "identical re-ingest must be a no-op"
    try:
        mem.ingest_view(dataclasses.replace(v1, degraded=True))
    except ImmutableRecordError:
        pass
    else:
        raise AssertionError("changed snapshot under an existing view_id was accepted")
    try:
        mem.raw_view("P-win", "v-missing")
    except MissingViewError:
        pass
    else:
        raise AssertionError("unknown view_id returned a view")
    # An interrupted ingest (memories written, sidecar not) is not a snapshot.
    mem._add("half-written", {"ewp": {"kind": "evidence", "proposition_id": "P-win", "view_id": "v3",
                                      "evidence_id": "e-half", "polarity": "opposes"}})
    assert mem.raw_view("P-win").view_id == "v2"
    assert "e-half" not in {e.evidence_id for e in mem.raw_view("P-win").evidence}
    # A proposition whose only ingest was interrupted has no snapshot to read.
    fresh = Mem0Adapter(FakeMem0(), user_id="u2", infer=False)
    fresh._add("half-written", {"ewp": {"kind": "evidence", "proposition_id": "P-new", "view_id": "v1",
                                        "evidence_id": "e-half", "polarity": "supports"}})
    lone = fresh.raw_view("P-new")
    assert lone.evidence == [] and lone.assertions == [], lone
    # Retrying an interrupted ingest: the orphans of the failed attempt, with
    # the same record ids, do not leak into the committed snapshot.
    v3 = dataclasses.replace(base, view_id="v3", evidence=base.evidence + [dataclasses.replace(base.evidence[0], evidence_id="e3")])
    for e in v3.evidence:
        mem._add(e.content, {"ewp": {"kind": "evidence", "proposition_id": "P-win", "view_id": "v3", "ingest_id": "crashed",
                                     "evidence_id": e.evidence_id, "polarity": e.polarity, "observed_at": e.observed_at}})
    mem.ingest_view(v3)
    assert canonical(mem.raw_view("P-win", "v3")) == canonical(v3), "retry after an interrupted ingest must return exactly v3"
    assert canonical(mem.raw_view("P-win")) == canonical(v3)
    # Two ingests racing on one new view_id: identical content is one
    # snapshot; different content is refused on read, never half-merged.
    race = Mem0Adapter(FakeMem0(), user_id="u3", infer=False)
    race.ingest_view(v1)
    sidecar_count = lambda m: sum(1 for r in m.client.rows if r["metadata"]["ewp"].get("kind") == "ewp_parked")
    other = Mem0Adapter(race.client, user_id="u3", infer=False)
    other._sidecars = lambda items: []  # the other writer checked before the first sidecar landed
    other.ingest_view(v1)
    assert sidecar_count(race) == 2 and canonical(race.raw_view("P-win", "v1")) == canonical(v1)
    other.ingest_view(dataclasses.replace(v1, degraded=True))
    try:
        race.raw_view("P-win", "v1")
    except LedgerError:
        pass
    else:
        raise AssertionError("two different snapshots committed under one view_id were read")
    # ...and the proposition is not wedged: a new view_id still ingests and reads.
    v4 = dataclasses.replace(v1, view_id="v4", degraded=True)
    race.ingest_view(v4)
    assert canonical(race.raw_view("P-win")) == canonical(v4)
    # A read that loses a committed memory (lagging index, partial page) is
    # refused, not returned as the complete snapshot.
    lossy = Mem0Adapter(mem.client, user_id="u1", infer=False)
    real_get_all = mem.client.get_all

    def drop_one(*, filters=None, top_k=20, **kw):
        payload = real_get_all(filters=filters, top_k=top_k, **kw)
        payload["results"] = [r for r in payload["results"] if r["metadata"]["ewp"].get("evidence_id") != "e3"]
        return payload

    lossy.client = type("Lossy", (), {"get_all": staticmethod(drop_one), "search": mem.client.search})()
    try:
        lossy.raw_view("P-win", "v3")
    except LedgerError:
        pass
    else:
        raise AssertionError("a partial Mem0 read was returned as the complete snapshot")
    # Search stays inside the chosen snapshot.
    found = mem.search_view("P-win", "Windows", view_id="v1")
    assert all(a.assertion_id == "a1" for a in found.assertions), found.assertions
    print("PASS Mem0 snapshots: exact v1/v2, latest, idempotent re-ingest, immutable ids, interrupted ingest ignored and retried, racing commits")


def test_stores_agree_on_snapshot_history() -> None:
    """The same sequence of snapshot writes is accepted or refused identically
    by every store: an id names one record across a proposition's snapshots."""
    import dataclasses
    from tempfile import TemporaryDirectory

    from ewp.fixtures import fixture_verified_current
    from ewp.sqlite_adapter import ImmutableRecordError
    from ewp.types import Conflict

    base = fixture_verified_current()
    base = dataclasses.replace(base, subjects=("server01", "srv-1"),
                               checks=[dataclasses.replace(base.checks[0], subjects=("server01", "srv-1"))])
    e1 = base.evidence[0]
    steps = [
        ("v1 original", dataclasses.replace(base, view_id="v1"), True),
        ("v2 redefines check k1", dataclasses.replace(base, view_id="v2", checks=[dataclasses.replace(base.checks[0], result="opposes")]), False),
        ("v3 adds e2, keeps a1", dataclasses.replace(base, view_id="v3", evidence=[e1, dataclasses.replace(e1, evidence_id="e2")]), True),
        ("v4 source with another lineage", dataclasses.replace(base, view_id="v4", evidence=[dataclasses.replace(
            e1, evidence_id="e3", source=dataclasses.replace(e1.source, lineage_id="L-other"))], assertions=[], checks=[]), False),
        ("v5 conflict c1 open", dataclasses.replace(base, view_id="v5", conflicts=[Conflict("c1", ("P-win",), "open")]), True),
        ("v6 widens c1 participants", dataclasses.replace(base, view_id="v6", conflicts=[Conflict("c1", ("P-win", "P-x"), "open")]), False),
        ("v7 resolves c1", dataclasses.replace(base, view_id="v7", conflicts=[Conflict("c1", ("P-win",), "resolved")]), True),
        ("v8 reordered v3", dataclasses.replace(base, view_id="v8", evidence=[dataclasses.replace(e1, evidence_id="e2"), e1]), True),
        ("v9 subjects reordered", dataclasses.replace(base, view_id="v9", subjects=("srv-1", "server01"),
                                                      checks=[dataclasses.replace(base.checks[0], subjects=("srv-1", "server01"))]), True),
        ("v1 again, identical", dataclasses.replace(base, view_id="v1"), True),
        ("v1 again, changed", dataclasses.replace(base, view_id="v1", degraded=True), False),
    ]
    with TemporaryDirectory() as tmp:
        stores = {
            "SQLite": SQLiteAdapter().load_view,
            "JSON": JsonFileAdapter(tmp).load_view,
            "Mem0": Mem0Adapter(FakeMem0(), user_id="u9", infer=False).ingest_view,
        }
        for label, view, should_store in steps:
            for name, write in stores.items():
                try:
                    write(view)
                    stored = True
                except ImmutableRecordError:
                    stored = False
                assert stored == should_store, f"{name}: {label} -> {'stored' if stored else 'refused'}"
    print(f"PASS SQLite, JSON, and Mem0 agree on {len(steps)} snapshot writes (ids are stable across snapshots)")


def main() -> int:
    test_every_fixture_through_every_adapter()
    test_every_field_round_trips()
    test_live_graphiti_parks_subjects()
    test_mem0_snapshots()
    test_stores_agree_on_snapshot_history()
    print("ADAPTER ROUND-TRIP SUITE PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
