"""v0.1 behavioral conformance. Schema serialization is not enough."""

from __future__ import annotations

import sys
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ewp.fixtures import (
    EVAL,
    EVAL_LATE,
    fixture_compression_full,
    fixture_compression_honest,
    fixture_derived,
    fixture_fork,
    fixture_lineage_clones,
    fixture_persona,
    fixture_premises_tentative,
    fixture_reinforcement,
    fixture_retrieval_complete,
    fixture_retrieval_degraded,
    fixture_superseded,
    fixture_verified_current,
)
from ewp.may_act import Action, RiskPolicy, may_act
from ewp.json_adapter import JsonFileAdapter
from ewp.sqlite_adapter import SQLiteAdapter
from ewp.types import Policy
from ewp.warrant import warrant_now

POLICY = Policy()


def eval_view(view, evaluated_at=EVAL):
    return warrant_now(view, POLICY, evaluated_at)


def test_1_reinforcement_invariance():
    w = eval_view(fixture_reinforcement())
    assert w.warrant.verification == "NONE"
    assert w.warrant.acceptance != "ACCEPTED"
    assert w.independent_lineage_count == 1


def test_2_fork_preservation():
    vx, vn = fixture_fork()
    wx, wn = eval_view(vx), eval_view(vn)
    assert wx.warrant.conflict == "OPEN"
    assert wn.warrant.conflict == "OPEN"
    assert wx.warrant.acceptance != "ACCEPTED"
    assert vx.assertions[0].text == "X"
    assert vn.assertions[0].text == "not X"
    assert vx.proposition_id != vn.proposition_id


def test_3_compression_monotonicity():
    rank = {"NONE": 0, "INDIRECT": 1, "EXTERNAL": 2, "HUMAN": 3}
    full = eval_view(fixture_compression_full())
    honest = eval_view(fixture_compression_honest())
    assert full.warrant.conflict == "OPEN"
    assert honest.warrant.sufficiency == "DEGRADED"
    assert rank[honest.warrant.verification] <= rank[full.warrant.verification]
    assert honest.warrant.strength <= full.warrant.strength + 1e-9


def test_4_retrieval_completeness():
    ok = eval_view(fixture_retrieval_complete())
    deg = eval_view(fixture_retrieval_degraded())
    assert ok.warrant.conflict == "OPEN"
    assert "en" in ok.opposing_evidence_ids
    assert deg.warrant.sufficiency == "DEGRADED"
    assert deg.omitted_sources == ["s2"]


def test_5_persona_non_authority():
    w = eval_view(fixture_persona())
    assert w.warrant.verification == "NONE"
    assert w.warrant.acceptance == "TENTATIVE"
    assert w.checks == []


def test_6_warrant_conservation():
    prem = eval_view(fixture_premises_tentative())
    derived = eval_view(fixture_derived())
    rank = {"NONE": 0, "INDIRECT": 1, "EXTERNAL": 2, "HUMAN": 3}
    assert rank[derived.warrant.verification] <= rank[prem.warrant.verification]
    assert derived.warrant.acceptance != "ACCEPTED"
    assert "P-occ" in derived.derived_from


def test_7_lineage_independence():
    w = eval_view(fixture_lineage_clones())
    assert w.independent_lineage_count == 1
    assert len(w.supporting_evidence_ids) == 4


def test_8_temporal_invalidation():
    current = eval_view(fixture_verified_current(), EVAL)
    later = eval_view(fixture_verified_current(), EVAL_LATE)
    superseded = eval_view(fixture_superseded())
    assert current.warrant.verification == "EXTERNAL"
    assert current.warrant.acceptance == "ACCEPTED"
    assert current.warrant.currency == "CURRENT"
    assert later.warrant.currency == "STALE"
    assert later.warrant.acceptance != "ACCEPTED"
    assert superseded.warrant.currency == "SUPERSEDED"
    assert superseded.superseded_by == ["P-new"]


def test_9_policy_reproducibility():
    view = fixture_verified_current()
    a = eval_view(view, EVAL).normalized()
    b = eval_view(view, EVAL).normalized()
    assert a == b
    c = eval_view(view, EVAL_LATE).normalized()
    assert c["evaluated_at"] != a["evaluated_at"]
    assert c["warrant"]["currency"] != a["warrant"]["currency"]


def test_10_store_independence_sqlite_roundtrip():
    view = fixture_verified_current()
    direct = eval_view(view).normalized()
    db = SQLiteAdapter()
    db.load_view(view)
    loaded = db.get_view(
        view.proposition_id,
        view.view_id,
        freshness_policy_seconds=view.freshness_policy_seconds,
    )
    via_store = eval_view(loaded).normalized()
    # view_id may be supplied by caller; compare epistemic payload
    for key in ("warrant", "independent_lineage_count", "stale", "checks", "supporting_evidence_ids"):
        assert direct[key] == via_store[key], key
    with TemporaryDirectory() as tmp:
        js = JsonFileAdapter(tmp)
        js.load_view(view)
        loaded_js = js.get_view(view.proposition_id, view.view_id)
        via_json = eval_view(loaded_js).normalized()
    for key in ("warrant", "independent_lineage_count", "stale", "checks", "supporting_evidence_ids"):
        assert direct[key] == via_json[key], f"json:{key}"



def test_10b_sqlite_persists_degraded_view_meta():
    view = fixture_retrieval_degraded()
    db = SQLiteAdapter()
    db.load_view(view)
    loaded = db.get_view(view.proposition_id, view.view_id)
    w = eval_view(loaded)
    assert loaded.degraded is True
    assert loaded.omitted_sources == view.omitted_sources
    assert loaded.retrieval_scope == view.retrieval_scope
    assert w.warrant.sufficiency == "DEGRADED"
    assert w.warrant.acceptance != "ACCEPTED"


def test_action_gate_is_separate():
    w = eval_view(fixture_verified_current())
    cancel = Action("cancel", "contract.cancel", reversible=False, risk="high")
    precool = Action("precool", "hvac.precool", reversible=True, risk="low")
    assert may_act(w, cancel, RiskPolicy()) == "MAY_ACT"
    disputed = eval_view(fixture_compression_full())
    assert may_act(disputed, cancel, RiskPolicy()) == "DENY"
    assert may_act(disputed, precool, RiskPolicy()) == "REQUIRE_CONFIRMATION"
    open_high = may_act(
        disputed,
        cancel,
        RiskPolicy(high_requires_accepted=False, high_requires_no_open_conflict=True),
    )
    assert open_high == "DENY"


if __name__ == "__main__":
    tests = [v for k, v in list(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
        except Exception as e:
            failed += 1
            print(f"FAIL {t.__name__}: {e}")
    raise SystemExit(failed)
