"""Pathological pack: Graphiti-local conclusions must not leak into warrant."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from protocol.fixtures import EVAL, EVAL_LATE
from protocol.graphiti_adapter import GraphitiAdapter
from protocol.graphiti_hostile import apply_hostile
from protocol.graphiti_ingest import ingest_view
from protocol.graphiti_records import FakeGraphitiStore
from protocol.pathological import PACK
from protocol.types import Policy
from protocol.warrant import warrant_now

POLICY = Policy()


def _prep(name, factory):
    view = factory()
    store = FakeGraphitiStore()
    ingest_view(store, view)
    proj = apply_hostile(name, store)
    raw = GraphitiAdapter(store).raw_view(view.proposition_id)
    w = warrant_now(raw, POLICY, EVAL)
    return view, store, proj, raw, w


def test_p1_false_supersession_not_inherited():
    _v, _s, proj, raw, w = _prep("p1-false-supersession", dict(PACK)["p1-false-supersession"])
    assert proj["invalidated"]
    assert w.warrant.currency != "SUPERSEDED"
    assert "graphiti.invalid_at" in raw.evidence[0].content


def test_p2_conflict_stays_open():
    _v, _s, proj, raw, w = _prep("p2-contradiction-open", dict(PACK)["p2-contradiction-open"])
    assert proj["invalidated"]
    assert w.warrant.conflict == "OPEN"
    assert len(raw.assertions) == 2


def test_p3_supersession_from_lineage_not_invalid_at():
    _v, _s, _p, raw, w = _prep("p3-real-upgrade", dict(PACK)["p3-real-upgrade"])
    assert w.warrant.currency == "SUPERSEDED"  # from parked lineage edges
    assert any(e.kind == "superseded_by" for e in raw.lineage)
    assert w.warrant.verification == "EXTERNAL"


def test_p4_collapse_degrades():
    view, store, proj, raw, w = _prep("p4-same-text-independent", dict(PACK)["p4-same-text-independent"])
    assert w.independent_lineage_count == 2
    search = GraphitiAdapter(store).search_view(view.proposition_id, "X", "X")
    sw = warrant_now(search, POLICY, EVAL)
    assert search.degraded or sw.warrant.sufficiency == "DEGRADED"
    assert proj["search_kept"]


def test_p5_one_lineage():
    _v, _s, _p, _r, w = _prep("p5-diff-text-one-lineage", dict(PACK)["p5-diff-text-one-lineage"])
    assert w.independent_lineage_count == 1


def test_p6_verified_not_displaced_by_current():
    _v, _s, proj, _r, w = _prep("p6-current-vs-verified", dict(PACK)["p6-current-vs-verified"])
    assert proj["current_facts"] == ["server01 runs Server 2022"]
    assert w.warrant.verification == "EXTERNAL"
    assert w.warrant.conflict == "OPEN"
    assert w.warrant.acceptance != "ACCEPTED"  # open conflict blocks acceptance


def test_p7_weak_invalidation_ignored():
    _v, _s, proj, _r, w = _prep("p7-weak-vs-strong", dict(PACK)["p7-weak-vs-strong"])
    assert proj["current_facts"] == ["not X"]
    assert w.warrant.verification == "EXTERNAL"
    assert w.warrant.conflict == "OPEN"


def test_p8_expiry_does_not_erase_check():
    _v, _s, proj, raw, w = _prep("p8-verify-survives-expiry", dict(PACK)["p8-verify-survives-expiry"])
    assert proj["invalidated"]
    assert raw.checks
    assert w.warrant.verification == "EXTERNAL"
    # freshness policy is 365d; EVAL is still current
    assert w.warrant.currency == "CURRENT"
    later = warrant_now(raw, POLICY, EVAL_LATE)
    assert later.warrant.verification == "EXTERNAL"


def test_p9_false_consensus_degraded():
    view, store, _p, raw, w = _prep("p9-false-consensus", dict(PACK)["p9-false-consensus"])
    assert w.warrant.conflict == "OPEN"
    search = GraphitiAdapter(store).search_view(view.proposition_id, "X")
    sw = warrant_now(search, POLICY, EVAL)
    assert sw.warrant.sufficiency == "DEGRADED"
    assert sw.warrant.strength <= w.warrant.strength


def test_p10_conflict_one_lineage():
    _v, _s, _p, _r, w = _prep("p10-same-lineage-conflict", dict(PACK)["p10-same-lineage-conflict"])
    assert w.warrant.conflict == "OPEN"
    assert w.independent_lineage_count == 1


def test_p11_canonical_is_not_verified():
    _v, _s, proj, _r, w = _prep("p11-maintenance-no-verify", dict(PACK)["p11-maintenance-no-verify"])
    assert proj["current_facts"] == ["X"]
    assert w.warrant.verification == "NONE"


def test_p12_cycle_exposes_evidence_not_truth():
    _v, _s, _p, raw, w = _prep("p12-invalidation-cycle", dict(PACK)["p12-invalidation-cycle"])
    assert len(raw.assertions) == 3
    assert w.warrant.conflict == "OPEN"
    assert w.warrant.verification == "NONE"


if __name__ == "__main__":
    failed = 0
    for n, fn in list(globals().items()):
        if n.startswith("test_"):
            try:
                fn()
                print(f"PASS {n}")
            except Exception as e:
                failed += 1
                print(f"FAIL {n}: {e}")
    raise SystemExit(failed)
