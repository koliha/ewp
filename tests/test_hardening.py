#!/usr/bin/env python3
"""Regression tests for 0.2.0 fixes: time, policy identity, enums, may_act, adapters, sqlite."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import dataclasses
import json

from ewp.classify import InvalidEvidenceView, parse_ts
from ewp.codec import view_from_dict
from ewp.fixtures import EVAL, T0, assertion, ev, fixture_verified_current, src
from ewp.graphiti_adapter import GraphitiAdapter
from ewp.graphiti_ingest import ingest_view
from ewp.graphiti_records import FakeEpisode, FakeGraphitiStore
from ewp.may_act import Action, RiskPolicy, may_act
from ewp.sqlite_adapter import ImmutableRecordError, SQLiteAdapter
from ewp.types import (
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
from ewp.warrant import warrant_now


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
    # The naive 18:31 records are read as UTC, so they are available at 21:00Z.
    assert w.supporting_evidence_ids == ["em"], w.supporting_evidence_ids
    assert w.warrant.acceptance == "TENTATIVE", w.warrant
    before = warrant_now(view, Policy(), "2026-09-21T18:00:00+00:00")
    assert before.warrant.acceptance == "UNACCEPTED", before.warrant
    print("PASS naive timestamps are UTC instants, compared against aware ones")


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


def _refused(fn) -> bool:
    try:
        fn()
    except ImmutableRecordError:
        return True
    return False


def test_sqlite_is_append_only():
    view = fixture_verified_current()
    db = SQLiteAdapter()
    db.load_view(view)
    db.load_view(view)  # identical snapshot: no-op
    flipped = dataclasses.replace(view.checks[0], result="opposes")
    # A ledger record cannot change, even under a new view id.
    assert _refused(lambda: db.load_view(dataclasses.replace(view, view_id="v-new", checks=[flipped])))
    # A snapshot cannot change under its own id.
    assert _refused(lambda: db.load_view(dataclasses.replace(view, degraded=True)))
    assert db.get_view(view.proposition_id, view.view_id).checks[0].result == "supports"
    # Conflict participants are fixed across views; status belongs to each snapshot.
    base = dict(assertions=[], evidence=[], checks=[])
    db.load_view(dataclasses.replace(view, view_id="v-open", conflicts=[Conflict("c1", ("P-win",), "open")], **base))
    db.load_view(dataclasses.replace(view, view_id="v-resolved", conflicts=[Conflict("c1", ("P-win",), "resolved")], **base))
    assert db.get_view("P-win", "v-open").conflicts[0].status == "open"
    assert db.get_view("P-win", "v-resolved").conflicts[0].status == "resolved"
    assert _refused(lambda: db.load_view(dataclasses.replace(
        view, view_id="v-widened", conflicts=[Conflict("c1", ("P-win", "P-other"), "open")], **base)))
    print("PASS sqlite: ledger records and snapshots are immutable; conflict participants fixed, status per snapshot")


def test_sqlite_views_are_snapshots():
    from ewp.sqlite_adapter import MissingViewError

    v1 = fixture_verified_current()
    v2 = dataclasses.replace(
        v1,
        view_id="v2",
        degraded=True,
        evidence=v1.evidence + [dataclasses.replace(v1.evidence[0], evidence_id="e2")],
    )
    db = SQLiteAdapter()
    db.load_view(v1)
    db.load_view(v2)
    old = db.get_view(v1.proposition_id, v1.view_id)
    assert old.view_id == "v-ver" and len(old.evidence) == 1 and old.degraded is False, old
    assert db.get_view(v1.proposition_id).view_id == "v2"
    grown = db.extend_view(v1.proposition_id, evidence=[dataclasses.replace(v1.evidence[0], evidence_id="e3")])
    assert db.get_view(v1.proposition_id).view_id == grown.view_id
    assert [e.evidence_id for e in grown.evidence] == ["e1", "e2", "e3"]
    assert len(db.get_view(v1.proposition_id, "v2").evidence) == 2
    assert db.view_ids(v1.proposition_id) == ["v-ver", "v2", grown.view_id]
    try:
        db.get_view("P-never-stored")
    except MissingViewError:
        pass
    else:
        raise AssertionError("missing proposition returned a view")
    print("PASS sqlite: get_view(pid, id) returns exactly that snapshot; extend_view makes a new latest")


def _as_proposition(view: EvidenceView, pid: str, **changes) -> EvidenceView:
    return dataclasses.replace(
        view,
        proposition_id=pid,
        assertions=[dataclasses.replace(a, proposition_id=pid) for a in view.assertions],
        evidence=[dataclasses.replace(e, proposition_id=pid) for e in view.evidence],
        **changes,
    )


def test_json_store_ids_cannot_collide_or_escape():
    import tempfile

    from ewp.json_adapter import JsonFileAdapter

    base = fixture_verified_current()
    with tempfile.TemporaryDirectory() as outer:
        root = Path(outer) / "store"
        store = JsonFileAdapter(root)
        store.load_view(_as_proposition(base, "a/b"))
        store.load_view(_as_proposition(base, "a_b", degraded=True))
        assert store.get_view("a/b").degraded is False, "a/b and a_b collided"
        assert store.get_view("a_b").degraded is True
        store.load_view(_as_proposition(base, "..\\..\\escaped"))
        store.load_view(_as_proposition(base, "../../escaped2"))
        outside = [p for p in Path(outer).rglob("*") if root not in p.parents and p != root]
        assert outside == [], outside
        bad = dataclasses.replace(base, conflicts=[Conflict("c", ("P-win",), "Open")])  # type: ignore[arg-type]
        try:
            store.load_view(bad)
        except InvalidEvidenceView:
            pass
        else:
            raise AssertionError("JSON store accepted status='Open'")
    print("PASS json store: hashed paths, no collisions or escapes, validates writes")


_APPENDER = r"""
import dataclasses, sys
sys.path.insert(0, sys.argv[1])
from ewp.fixtures import fixture_verified_current
from ewp.sqlite_adapter import SQLiteAdapter
base = fixture_verified_current().evidence[0]
with SQLiteAdapter(sys.argv[2]) as db:
    for i in range(int(sys.argv[4])):
        db.extend_view("P-win", evidence=[dataclasses.replace(base, evidence_id=f"{sys.argv[3]}-{i}")])
"""


def test_sqlite_concurrent_processes_do_not_lose_appends():
    import subprocess
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        db = str(Path(tmp) / "ledger.sqlite")
        with SQLiteAdapter(db) as store:
            store.load_view(fixture_verified_current())
        procs = [
            subprocess.Popen([sys.executable, "-c", _APPENDER, str(Path(__file__).resolve().parents[1]), db, f"p{n}", "10"])
            for n in range(4)
        ]
        codes = [p.wait(timeout=120) for p in procs]
        assert codes == [0, 0, 0, 0], codes
        with SQLiteAdapter(db) as store:
            latest = store.get_view("P-win")
            snapshots = len(store.view_ids("P-win"))
        ids = {e.evidence_id for e in latest.evidence}
        expected = {"e1"} | {f"p{n}-{i}" for n in range(4) for i in range(10)}
        assert ids == expected, sorted(expected - ids)
        assert snapshots == 41, snapshots
    print("PASS sqlite: 4 processes x 10 concurrent appends, latest snapshot has all 40")


def test_sqlite_read_only_ledger():
    import tempfile

    from ewp.sqlite_adapter import LedgerError

    with tempfile.TemporaryDirectory() as tmp:
        missing = Path(tmp) / "typo" / "ledger.sqlite"
        try:
            SQLiteAdapter(str(missing), read_only=True)
        except LedgerError as exc:
            assert "ledger not found" in str(exc)
        else:
            raise AssertionError("read-only open of a missing ledger succeeded")
        assert not missing.exists() and not missing.parent.exists(), "read-only open created files"
        db = str(Path(tmp) / "ledger.sqlite")
        with SQLiteAdapter(db) as store:
            store.load_view(fixture_verified_current())
        with SQLiteAdapter(db, read_only=True) as ro:
            assert ro.get_view("P-win").view_id == "v-ver"
            try:
                ro.load_view(dataclasses.replace(fixture_verified_current(), view_id="v2"))
            except LedgerError:
                pass
            else:
                raise AssertionError("read-only ledger accepted a write")
            import sqlite3

            try:
                ro.conn.execute("DELETE FROM views")
            except sqlite3.OperationalError:
                pass
            else:
                raise AssertionError("read-only connection allowed a raw write")
    print("PASS sqlite: read-only ledger refuses a missing path, writes, and raw SQL writes")


def test_conflict_ids_are_per_proposition_and_order_is_not_content():
    s = src("s", "L")
    p1 = EvidenceView("v", "P1", assertions=[assertion("a", "P1", "X", s)], conflicts=[Conflict("c1", ("P1",), "open")])
    p2 = EvidenceView("v", "P2", assertions=[assertion("a", "P2", "Y", s)], conflicts=[Conflict("c1", ("P2",), "open")])
    db = SQLiteAdapter()
    db.load_view(p1)
    db.load_view(p2)
    assert db.get_view("P2").conflicts[0].proposition_ids == ("P2",)
    two = EvidenceView("v-two", "P1", assertions=[assertion("a", "P1", "X", s), assertion("b", "P1", "Z", s)])
    db.load_view(two)
    db.load_view(dataclasses.replace(two, assertions=list(reversed(two.assertions))))  # same content: no-op
    from ewp.codec import content_view_id

    assert content_view_id(two) == content_view_id(dataclasses.replace(two, assertions=list(reversed(two.assertions))))
    print("PASS conflict ids are per proposition; record order is not content (ids, SQLite)")


def test_codec_normalizes_optional_ids():
    raw = fixture_verified_current().to_dict()
    for part in ("assertions", "evidence", "checks"):
        for record in raw[part]:
            record["source"]["extractor_id"] = 7
            record["source"]["parent_source_id"] = 12
    view = view_from_dict(raw)
    assert view.assertions[0].source.extractor_id == "7" and view.checks[0].source.parent_source_id == "12"
    db = SQLiteAdapter()
    db.load_view(view)
    db.load_view(view_from_dict(raw))  # identical re-put: a no-op, not a "change"
    assert db.get_view("P-win").assertions[0].source.extractor_id == "7"
    print("PASS codec normalizes optional source ids; identical re-put through SQLite is a no-op")


def test_json_store_concurrent_writers_keep_every_snapshot():
    """Without a lock, two writers each rewrote latest.json from what they
    read and one view_id vanished from the history. Readers run alongside:
    on Windows a replace fails while any process has the file open, and an
    open can fail mid-replace, so neither may surface as an error."""
    import tempfile
    import threading

    from ewp.json_adapter import JsonFileAdapter

    base = fixture_verified_current()
    with tempfile.TemporaryDirectory() as tmp:
        JsonFileAdapter(tmp).load_view(base)
        start = threading.Barrier(12)
        stop = threading.Event()
        errors: list[BaseException] = []

        def writer(n: int) -> None:
            store = JsonFileAdapter(tmp)
            start.wait()
            try:
                for i in range(10):
                    store.load_view(dataclasses.replace(base, view_id=f"w{n}-{i}"))
            except BaseException as exc:  # surfaced below
                errors.append(exc)

        def reader() -> None:
            store = JsonFileAdapter(tmp)
            start.wait()
            try:
                while not stop.is_set():
                    store.view_ids(base.proposition_id)
                    store.get_view(base.proposition_id)
            except BaseException as exc:  # surfaced below
                errors.append(exc)

        writers = [threading.Thread(target=writer, args=(n,)) for n in range(8)]
        readers = [threading.Thread(target=reader) for _ in range(4)]
        for t in writers + readers:
            t.start()
        for t in writers:
            t.join()
        stop.set()
        for t in readers:
            t.join()
        assert not errors, errors
        ids = JsonFileAdapter(tmp).view_ids(base.proposition_id)
        assert len(ids) == 81 and len(set(ids)) == 81, (len(ids), len(set(ids)))
    print("PASS JSON store: concurrent writers and readers keep every snapshot in the history")


def test_json_store_recovers_from_interrupted_writes():
    """A snapshot is committed once its view_id is in the history. A retry
    after a crash replaces a partial file, or finishes a write whose history
    update was lost; a damaged committed file is an error, not a no-op."""
    import tempfile

    from ewp.codec import canonical_dict
    from ewp.json_adapter import JsonFileAdapter, _key
    from ewp.sqlite_adapter import LedgerError, MissingViewError

    base = fixture_verified_current()
    v2 = dataclasses.replace(base, view_id="v2", degraded=True)
    with tempfile.TemporaryDirectory() as tmp:
        store = JsonFileAdapter(tmp)
        store.load_view(base)
        snap = store._pdir(base.proposition_id) / "views" / f"{_key('v2')}.json"

        # 1. crashed mid-write: a partial file, not in the history
        snap.write_text('{"claim": "P-win", "view_me', encoding="utf-8")
        try:
            store.get_view(base.proposition_id, "v2")
        except MissingViewError:
            pass
        else:
            raise AssertionError("an uncommitted file was read as a snapshot")
        store.load_view(v2)
        assert canonical_dict(store.get_view(base.proposition_id, "v2")) == canonical_dict(v2)
        assert store.view_ids(base.proposition_id) == [base.view_id, "v2"]

        # 2. crashed after the file, before the history: the retry finishes the commit
        v3 = dataclasses.replace(base, view_id="v3")
        full = store._pdir(base.proposition_id) / "views" / f"{_key('v3')}.json"
        history = store.view_ids(base.proposition_id)
        store.load_view(v3)
        (store._pdir(base.proposition_id) / "latest.json").write_text(
            json.dumps({"claim": base.proposition_id, "view_ids": history}), encoding="utf-8")
        assert full.exists() and "v3" not in store.view_ids(base.proposition_id)
        store.load_view(v3)
        assert store.view_ids(base.proposition_id)[-1] == "v3"

        # 2b. finishing an interrupted commit still checks record ids against
        # the committed snapshots: an orphan that reuses an id for other content
        # must not be committed by the retry
        clash = dataclasses.replace(base, view_id="v4", assertions=[
            dataclasses.replace(base.assertions[0], text="server01 runs Windows Server 2019")])
        orphan = store._pdir(base.proposition_id) / "views" / f"{_key('v4')}.json"
        store_for_orphan = JsonFileAdapter(tmp)
        store_for_orphan.view_ids = lambda pid: []  # write the file as if no history existed, then "crash"
        store_for_orphan._append_history = lambda *a, **k: None
        store_for_orphan.load_view(clash)
        assert orphan.exists() and "v4" not in store.view_ids(base.proposition_id)
        try:
            store.load_view(clash)
        except ImmutableRecordError:
            pass
        else:
            raise AssertionError("an orphan reusing a committed record id was committed by the retry")
        assert "v4" not in store.view_ids(base.proposition_id)

        # 2c. an orphan is not a snapshot: a corrected retry under the same
        # view_id replaces it (it used to be refused as immutable)
        corrected = dataclasses.replace(base, view_id="v4", degraded=True)
        store.load_view(corrected)
        assert canonical_dict(store.get_view(base.proposition_id, "v4")) == canonical_dict(corrected)
        assert store.view_ids(base.proposition_id)[-1] == "v4"

        # 3. a committed snapshot that is unreadable is damage, never overwritten
        snap.write_text("garbage", encoding="utf-8")
        try:
            store.load_view(v2)
        except LedgerError:
            pass
        else:
            raise AssertionError("a damaged committed snapshot was silently rewritten or accepted")
    print("PASS JSON store: partial and half-committed writes recover on retry; damaged snapshots are errors")


def test_snapshot_reads_have_no_overrides():
    """(proposition_id, view_id) reads return exactly the stored snapshot.
    A view with other completeness metadata is a new snapshot, not a read option."""
    import tempfile

    from ewp.json_adapter import JsonFileAdapter
    from ewp.sqlite_adapter import SQLiteAdapter

    base = fixture_verified_current()
    with tempfile.TemporaryDirectory() as tmp:
        for store in (SQLiteAdapter(), JsonFileAdapter(tmp)):
            store.load_view(base)
            for override in ({"degraded": False}, {"freshness_policy_seconds": 10**9},
                             {"retrieval_scope": "complete"}, {"omitted_sources": []}):
                try:
                    store.get_view(base.proposition_id, base.view_id, **override)
                except TypeError:
                    continue
                raise AssertionError(f"{type(store).__name__}.get_view accepted {override}")
    print("PASS snapshot reads take no completeness overrides")


def test_kernel_refuses_malformed_record_fields():
    """The Python API fails closed like the codec: "" or {} is not an empty
    record list, and both evaluators refuse rather than evaluate."""
    from ewp.classify import InvalidEvidenceView
    from ewp.codec import view_from_dict
    from ewp.warrant_b import axes_only

    for name, value in (("checks", ""), ("checks", None), ("lineage", {}), ("assertions", "ab"), ("evidence", [object()])):
        view = fixture_verified_current()
        setattr(view, name, value)
        for evaluate in (lambda v: warrant_now(v, Policy(), EVAL), lambda v: axes_only(v, Policy(), EVAL)):
            try:
                evaluate(view)
            except InvalidEvidenceView:
                continue
            raise AssertionError(f"{name}={value!r} was evaluated")
    for attr, value in (("proposition_id", ""), ("proposition_id", None), ("view_id", 5)):
        view = fixture_verified_current()
        setattr(view, attr, value)
        try:
            warrant_now(view, Policy(), EVAL)
        except InvalidEvidenceView:
            continue
        raise AssertionError(f"{attr}={value!r} was evaluated")
    empty = dataclasses.replace(fixture_verified_current(), evidence=())
    warrant_now(empty, Policy(), EVAL)  # an empty tuple is an empty list
    d = fixture_verified_current().to_dict()
    for bad in ({}, False, [1], 1.5):
        try:
            view_from_dict(dict(d, view_id=bad))
        except InvalidEvidenceView:
            continue
        raise AssertionError(f"view_id={bad!r} was accepted")
    assert view_from_dict(dict(d, view_id="")).view_id.startswith("v-"), "empty view_id is derived from content"
    assert view_from_dict(dict(d, view_id=7)).view_id == "7"
    base = fixture_verified_current()
    no_hash = lambda r: dataclasses.replace(r, source=dataclasses.replace(r.source, content_hash=None))
    for broken in (
        dataclasses.replace(base, assertions=[no_hash(a) for a in base.assertions],
                            evidence=[no_hash(e) for e in base.evidence], checks=[no_hash(c) for c in base.checks]),
        dataclasses.replace(base, checks=[dataclasses.replace(c, method=None) for c in base.checks]),
        dataclasses.replace(base, evidence=[dataclasses.replace(e, content=None) for e in base.evidence]),
        dataclasses.replace(base, assertions=[dataclasses.replace(a, source="s1") for a in base.assertions]),
        dataclasses.replace(base, assertions=[dataclasses.replace(a, assertion_confidence=True) for a in base.assertions]),
    ):
        for evaluate in (lambda v: warrant_now(v, Policy(), EVAL), lambda v: axes_only(v, Policy(), EVAL)):
            try:
                evaluate(broken)
            except InvalidEvidenceView:
                continue
            raise AssertionError("a view missing required fields was evaluated")
    # An integer too large for a float is refused, not a crash, by the codec,
    # the kernel, and the third evaluator.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "docs" / "implementer"))
    import third_eval

    huge = json.loads(json.dumps(fixture_verified_current().to_dict()))
    huge["assertions"][0]["assertion_confidence"] = 10**400
    try:
        warrant_now(view_from_dict(huge), Policy(), EVAL)
    except InvalidEvidenceView:
        pass
    else:
        raise AssertionError("a confidence no float can hold was evaluated")
    try:
        third_eval.validate(dict(huge, evaluated_at=EVAL))
    except third_eval.InvalidView:
        pass
    else:
        raise AssertionError("the third evaluator accepted a confidence no float can hold")
    print("PASS kernel and codec refuse malformed record fields, missing required fields, empty proposition_id, non-id view_id, huge confidence")


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
    test_sqlite_views_are_snapshots()
    test_json_store_ids_cannot_collide_or_escape()
    test_sqlite_concurrent_processes_do_not_lose_appends()
    test_sqlite_read_only_ledger()
    test_conflict_ids_are_per_proposition_and_order_is_not_content()
    test_codec_normalizes_optional_ids()
    test_snapshot_reads_have_no_overrides()
    test_json_store_concurrent_writers_keep_every_snapshot()
    test_json_store_recovers_from_interrupted_writes()
    test_kernel_refuses_malformed_record_fields()
    print("HARDENING SUITE PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
