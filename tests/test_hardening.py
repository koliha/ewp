#!/usr/bin/env python3
"""Pre-release 0.2.0 holes: time, policy identity, enums, may_act, adapters, sqlite."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import dataclasses
import json

from protocol.classify import InvalidEvidenceView, parse_ts
from protocol.codec import view_from_dict
from protocol.fixtures import EVAL, T0, assertion, ev, fixture_verified_current, src
from protocol.graphiti_adapter import GraphitiAdapter
from protocol.graphiti_ingest import ingest_view
from protocol.graphiti_records import FakeEpisode, FakeGraphitiStore
from protocol.may_act import Action, RiskPolicy, may_act
from protocol.sqlite_adapter import ImmutableRecordError, SQLiteAdapter
from protocol.types import (
    Assertion,
    Conflict,
    EvidenceItem,
    EvidenceView,
    LineageEdge,
    Policy,
    VerificationCheck,
    WarrantAxes,
    WarrantView,
)
from protocol.warrant import warrant_now


def test_future_assertion_and_evidence_not_available_at_t():
    future = "2026-12-01T00:00:00+00:00"
    s = src("sfut", "L-fut", "tool")
    view = EvidenceView(
        "v-future-row",
        "P-future",
        assertions=[
            Assertion("af", "P-future", "X", "agent", 0.9, s, future),
        ],
        evidence=[
            EvidenceItem("ef", "P-future", "supports", s, "X", future),
        ],
    )
    w = warrant_now(view, Policy(), EVAL)
    assert w.warrant.acceptance == "UNACCEPTED", w.warrant
    assert w.warrant.sufficiency == "INSUFFICIENT", w.warrant
    assert w.supporting_evidence_ids == []
    print("PASS future assertion+evidence unavailable at T")


def test_naive_and_aware_timestamps_compare():
    naive = parse_ts("2026-09-21T18:31:00")
    aware = parse_ts("2026-09-21T21:00:00+00:00")
    assert naive.tzinfo is not None
    assert naive < aware
    s = src("smix", "L-mix")
    view = EvidenceView(
        "v-mix",
        "P-mix",
        assertions=[Assertion("am", "P-mix", "X", "agent", 0.9, s, "2026-09-21T18:31:00")],
        evidence=[EvidenceItem("em", "P-mix", "supports", s, "X", "2026-09-21T18:31:00")],
    )
    w = warrant_now(view, Policy(), "2026-09-21T21:00:00+00:00")
    assert w.warrant.acceptance in {"TENTATIVE", "UNACCEPTED", "ACCEPTED"}
    print("PASS naive vs aware timestamps do not crash")


def test_unknown_policy_rejected():
    view = fixture_verified_current()
    try:
        warrant_now(view, Policy(policy_id="reference-v2", version="v99"), EVAL)
    except ValueError as exc:
        assert "unknown policy" in str(exc)
        print("PASS unknown policy version rejected")
        return
    raise AssertionError("expected ValueError")


def test_may_act_flags_are_live():
    base = warrant_now(fixture_verified_current(), Policy(), EVAL)
    forged = WarrantView(
        proposition_id="P-x",
        view_id="forged",
        policy_id="reference-v2",
        policy_version="reference-v2",
        evaluated_at=EVAL,
        warrant=WarrantAxes(
            acceptance="TENTATIVE",
            conflict="OPEN",
            verification="EXTERNAL",
            currency="CURRENT",
            sufficiency="SUFFICIENT",
            strength=0.0,
            rationale_codes=[],
        ),
        supporting_evidence_ids=[],
        opposing_evidence_ids=[],
        independent_lineage_count=1,
        checks=[],
        freshest_check=None,
        stale=False,
        open_conflicts=["c1"],
        resolved_conflicts=[],
        omitted_sources=[],
        derived_from=[],
        supersedes=[],
        superseded_by=[],
    )
    high = Action("x", "x", reversible=True, risk="high")
    deny = may_act(
        forged,
        high,
        RiskPolicy(high_requires_accepted=False, high_requires_no_open_conflict=True),
    )
    assert deny == "DENY", deny
    allow = may_act(
        forged,
        high,
        RiskPolicy(high_requires_accepted=False, high_requires_no_open_conflict=False),
    )
    assert allow == "MAY_ACT", allow
    assert may_act(base, high, RiskPolicy()) == "MAY_ACT"
    print("PASS high_requires_no_open_conflict is live")


def test_sqlite_lineage_not_duplicated():
    view = fixture_verified_current()
    view.lineage = [LineageEdge(view.proposition_id, "other", "derived_from")]
    db = SQLiteAdapter()
    db.load_view(view)
    db.load_view(view)
    loaded = db.get_view(view.proposition_id, view.view_id)
    assert len(loaded.lineage) == 1, loaded.lineage
    print("PASS sqlite lineage unique on reload")


def test_parked_sidecar_requires_proposition_id():
    store = FakeGraphitiStore()
    store.add_episode(
        FakeEpisode(
            uuid="orphan-parked",
            content="ewp-parked",
            created_at=T0,
            metadata={
                "kind": "ewp_parked",
                "checks": [
                    {
                        "check_id": "steal",
                        "method": "winrm",
                        "scope": "x",
                        "source": {
                            "source_id": "s",
                            "lineage_id": "L",
                            "origin_type": "tool",
                            "origin_locator": "l",
                            "snapshot_id": "sn",
                            "content_hash": "h",
                            "observed_at": T0,
                        },
                        "observed_at": T0,
                        "result": "supports",
                    }
                ],
            },
        )
    )
    adapter = GraphitiAdapter(store)
    view = adapter.raw_view("P-unrelated")
    assert view.checks == [], view.checks
    print("PASS parked sidecar without matching proposition_id is ignored")


def test_opposing_evidence_becomes_graphiti_edge():
    s1, s2 = src("s1", "L1"), src("s2", "L2")
    view = EvidenceView(
        "v-ret-ok",
        "P-x",
        assertions=[assertion("ax", "P-x", "X", s1)],
        evidence=[ev("ex", "P-x", "supports", s1, "X"), ev("en", "P-x", "opposes", s2, "not X")],
    )
    store = FakeGraphitiStore()
    ingest_view(store, view)
    raw = GraphitiAdapter(store).raw_view("P-x")
    polarities = {e.polarity for e in raw.evidence}
    lineages = {e.source.lineage_id for e in raw.evidence} | {a.source.lineage_id for a in raw.assertions}
    assert "opposes" in polarities, raw.evidence
    assert lineages == {"L1", "L2"}, lineages
    w = warrant_now(raw, Policy(), EVAL)
    assert w.independent_lineage_count == 2, w.independent_lineage_count
    print("PASS opposing evidence-only lineage becomes a Graphiti edge")


def test_scope_requires_declared_subjects():
    s = src("winrm", "L-obs", "tool")
    scraped = EvidenceView(
        "v-scrape",
        "P-win",
        assertions=[assertion("a1", "P-win", "server01 runs Windows Server 2022", s)],
        evidence=[ev("e1", "P-win", "supports", s, "Get-ComputerInfo server01")],
        checks=[VerificationCheck("k1", "tool_observation", "server02", s, "2026-09-21T18:31:00+00:00", "supports")],
    )
    bound = EvidenceView(
        "v-bound",
        "P-win",
        assertions=scraped.assertions,
        evidence=scraped.evidence,
        checks=[
            VerificationCheck(
                "k1",
                "tool_observation",
                "server02",
                s,
                "2026-09-21T18:31:00+00:00",
                "supports",
                subjects=("server02",),
            )
        ],
        subjects=("server01",),
    )
    w_scrape = warrant_now(scraped, Policy(), EVAL)
    w_bound = warrant_now(bound, Policy(), EVAL)
    assert w_scrape.warrant.verification == "EXTERNAL", w_scrape.warrant
    assert w_bound.warrant.verification == "INDIRECT", w_bound.warrant
    print("PASS scope caps only from declared subjects[], not regex scrape")


def test_reference_v1_is_not_this_evaluator():
    try:
        warrant_now(fixture_verified_current(), Policy("reference-v1", "reference-v1"), EVAL)
    except ValueError:
        print("PASS reference-v1 identity refused: semantics changed, name changed")
        return
    raise AssertionError("reference-v1 must not be accepted by the reference-v2 evaluator")


def test_unknown_enum_values_are_refused():
    base = fixture_verified_current().to_dict()
    cases = []
    bad = json.loads(json.dumps(base)); bad["checks"][0]["result"] = "pending"; cases.append(("result", bad))
    bad = json.loads(json.dumps(base)); bad["evidence"][0]["polarity"] = "oppose"; cases.append(("polarity", bad))
    bad = json.loads(json.dumps(base)); bad["conflicts"] = [{"conflict_id": "c", "proposition_ids": ["P-win"], "status": "Open"}]; cases.append(("status", bad))
    bad = json.loads(json.dumps(base)); bad["lineage"] = [{"from_id": "P-win", "to_id": "P-2", "kind": "replaced_by"}]; cases.append(("kind", bad))
    for label, raw in cases:
        try:
            view_from_dict(raw)
        except InvalidEvidenceView:
            pass
        else:
            raise AssertionError(f"codec accepted unknown {label}")
    # The evaluator refuses too, for views built without the codec.
    view = fixture_verified_current()
    view.checks = [dataclasses.replace(view.checks[0], result="pending")]
    try:
        warrant_now(view, Policy(), EVAL)
    except InvalidEvidenceView:
        print("PASS unknown result/polarity/status/kind refused by codec and evaluator")
        return
    raise AssertionError("evaluator evaluated an unknown result")


def test_may_act_superseded_and_unknown_risk():
    view = fixture_verified_current()
    view.lineage = [LineageEdge(view.proposition_id, "P-newer", "superseded_by")]
    w = warrant_now(view, Policy(), EVAL)
    assert w.warrant.currency == "SUPERSEDED"
    assert may_act(w, Action("a", "k", True, "low"), RiskPolicy()) == "REQUIRE_CONFIRMATION"
    assert may_act(w, Action("a", "k", True, "high"), RiskPolicy(high_requires_accepted=False)) == "DENY"
    try:
        may_act(w, Action("a", "k", True, "critical"), RiskPolicy())  # type: ignore[arg-type]
    except ValueError:
        print("PASS may_act: superseded needs confirmation; unknown risk refused")
        return
    raise AssertionError("unknown risk level accepted")


def test_sqlite_isolates_propositions_sharing_ids():
    # Same view_id, assertion ids, check ids, and source ids; different propositions.
    p1 = dataclasses.replace(fixture_verified_current(), view_id="mcp", degraded=True)
    s = src("winrm", "L-other", "document")
    p2 = EvidenceView(
        "mcp",
        "P-other",
        assertions=[assertion("a1", "P-other", "something else", s)],
        evidence=[ev("e1", "P-other", "supports", s, "other")],
        checks=[VerificationCheck("k1", "inference", "x", s, "2026-09-21T18:31:00+00:00", "supports")],
        degraded=False,
    )
    db = SQLiteAdapter()
    db.load_view(p1)
    db.load_view(p2)
    back1 = db.get_view(p1.proposition_id, "mcp")
    back2 = db.get_view(p2.proposition_id, "mcp")
    assert back1.degraded is True, "P1 took P2's completeness metadata"
    assert back1.assertions[0].text == p1.assertions[0].text
    assert back1.checks[0].source.origin_type == "tool", back1.checks[0].source
    assert back2.checks[0].method == "inference"
    assert warrant_now(back1, Policy(), EVAL).warrant.acceptance == "TENTATIVE"
    print("PASS sqlite partitions view metadata and records by proposition")


def test_sqlite_is_append_only():
    view = fixture_verified_current()
    db = SQLiteAdapter()
    db.load_view(view)
    downgraded = dataclasses.replace(
        view,
        assertions=[],
        evidence=[],
        checks=[dataclasses.replace(view.checks[0], result="opposes")],
    )
    try:
        db.load_view(downgraded)
    except ImmutableRecordError:
        pass
    else:
        raise AssertionError("existing check was overwritten")
    assert db.get_view(view.proposition_id, view.view_id).checks[0].result == "supports"
    # Conflict participants are fixed; status may change.
    db.load_view(dataclasses.replace(view, assertions=[], evidence=[], checks=[], conflicts=[Conflict("c1", ("P-win",), "open")]))
    db.load_view(dataclasses.replace(view, assertions=[], evidence=[], checks=[], conflicts=[Conflict("c1", ("P-win",), "resolved")]))
    try:
        db.load_view(dataclasses.replace(view, assertions=[], evidence=[], checks=[], conflicts=[Conflict("c1", ("P-other",), "open")]))
    except ImmutableRecordError:
        print("PASS sqlite refuses overwrites; conflict participants fixed, status may change")
        return
    raise AssertionError("conflict participants were rewritten")


def main() -> int:
    test_future_assertion_and_evidence_not_available_at_t()
    test_naive_and_aware_timestamps_compare()
    test_unknown_policy_rejected()
    test_may_act_flags_are_live()
    test_sqlite_lineage_not_duplicated()
    test_parked_sidecar_requires_proposition_id()
    test_opposing_evidence_becomes_graphiti_edge()
    test_scope_requires_declared_subjects()
    test_reference_v1_is_not_this_evaluator()
    test_unknown_enum_values_are_refused()
    test_may_act_superseded_and_unknown_risk()
    test_sqlite_isolates_propositions_sharing_ids()
    test_sqlite_is_append_only()
    print("HARDENING SUITE PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
