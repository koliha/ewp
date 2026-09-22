"""Graphiti adapter: evidence in, conclusions refused."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from protocol.fixtures import EVAL, EVAL_LATE
from protocol.graphiti_adapter import GraphitiAdapter
from protocol.graphiti_records import FakeEntityEdge, FakeEpisode, FakeGraphitiStore
from protocol.types import Policy
from protocol.warrant import warrant_now

POLICY = Policy()
FACT = "server01 runs Windows Server 2022"
PID = "P-win"


def _eval(view, at=EVAL):
    return warrant_now(view, POLICY, at)


def test_invalid_at_is_not_supersession():
    store = FakeGraphitiStore()
    store.add_episode(FakeEpisode("ep1", "obs", "2026-09-21T18:00:00+00:00", metadata={"lineage_id": "L1"}))
    store.add_edge(
        FakeEntityEdge(
            uuid="e1",
            fact=FACT,
            group_id="g",
            episodes=["ep1"],
            valid_at="2026-01-01T00:00:00+00:00",
            invalid_at="2026-09-01T00:00:00+00:00",
            expired_at="2026-09-02T00:00:00+00:00",
            created_at="2026-09-21T18:00:00+00:00",
            reference_time="2026-09-21T18:00:00+00:00",
        )
    )
    view = GraphitiAdapter(store).raw_view(PID, FACT)
    w = _eval(view)
    assert w.warrant.currency != "SUPERSEDED"
    assert w.warrant.verification == "NONE"
    assert "graphiti.invalid_at" in view.evidence[0].content
    assert w.superseded_by == []


def test_valid_at_is_not_verification():
    store = FakeGraphitiStore()
    store.add_episode(FakeEpisode("ep1", "extracted", "2026-09-21T18:00:00+00:00", metadata={"lineage_id": "L1"}))
    store.add_edge(
        FakeEntityEdge(
            uuid="e1",
            fact=FACT,
            group_id="g",
            episodes=["ep1"],
            valid_at="2022-01-01T00:00:00+00:00",
            reference_time="2026-09-21T18:00:00+00:00",
        )
    )
    w = _eval(GraphitiAdapter(store).raw_view(PID, FACT))
    assert w.warrant.verification == "NONE"
    assert w.checks == []
    assert w.warrant.acceptance != "ACCEPTED"


def test_lineage_from_episode_metadata():
    store = FakeGraphitiStore()
    for i in "abc":
        store.add_episode(
            FakeEpisode(f"ep{i}", "reuters copy", "2026-09-01T00:00:00+00:00", metadata={"lineage_id": "sha256:reuters"})
        )
    store.add_edge(
        FakeEntityEdge(
            uuid="e1",
            fact="X",
            group_id="g",
            episodes=["epa", "epb", "epc"],
            reference_time="2026-09-01T00:00:00+00:00",
        )
    )
    w = _eval(GraphitiAdapter(store).raw_view("P-x", "X"))
    assert w.independent_lineage_count == 1


def test_missing_lineage_does_not_invent_a_shared_one():
    store = FakeGraphitiStore()
    store.add_episode(FakeEpisode("epA", "src A", "2026-09-01T00:00:00+00:00"))
    store.add_episode(FakeEpisode("epB", "src B", "2026-09-01T00:00:00+00:00"))
    store.add_edge(
        FakeEntityEdge(
            uuid="e1",
            fact="X",
            group_id="g",
            episodes=["epA", "epB"],
            reference_time="2026-09-01T00:00:00+00:00",
        )
    )
    w = _eval(GraphitiAdapter(store).raw_view("P-x", "X"))
    # Absent metadata ⇒ each episode is its own lineage key (episode uuid).
    # Adapter must not invent a shared lineage, nor collapse them.
    assert w.independent_lineage_count == 2


def test_retrieval_collapse_is_degraded():
    store = FakeGraphitiStore()
    store.add_episode(FakeEpisode("ep1", "a", "2026-09-01T00:00:00+00:00", metadata={"lineage_id": "L1"}))
    store.add_episode(FakeEpisode("ep2", "b", "2026-09-01T00:00:00+00:00", metadata={"lineage_id": "L2"}))
    store.add_edge(FakeEntityEdge("e1", FACT, "g", ["ep1"], reference_time="2026-09-01T00:00:00+00:00"))
    store.add_edge(FakeEntityEdge("e2", FACT, "g", ["ep2"], reference_time="2026-09-01T00:00:00+00:00"))
    store.search_hits[FACT] = ["e1"]  # same fact text, other UUID dropped
    raw = GraphitiAdapter(store).raw_view(PID, FACT)
    hit = GraphitiAdapter(store).search_view(PID, FACT, FACT)
    wr, ws = _eval(raw), _eval(hit)
    assert raw.degraded is False
    assert hit.degraded is True
    assert ws.warrant.sufficiency == "DEGRADED"
    assert wr.independent_lineage_count == 2
    assert ws.warrant.strength <= wr.warrant.strength


def test_raw_graphiti_does_not_raise_verification_over_time():
    store = FakeGraphitiStore()
    store.add_episode(FakeEpisode("ep1", "obs", "2026-09-21T18:00:00+00:00", metadata={"lineage_id": "L1"}))
    store.add_edge(
        FakeEntityEdge(
            uuid="e1",
            fact=FACT,
            group_id="g",
            episodes=["ep1"],
            valid_at="2026-01-01T00:00:00+00:00",
            reference_time="2026-09-21T18:00:00+00:00",
        )
    )
    view = GraphitiAdapter(store).raw_view(PID, FACT)
    now = _eval(view, EVAL)
    later = _eval(view, EVAL_LATE)
    assert now.warrant.verification == later.warrant.verification == "NONE"


if __name__ == "__main__":
    failed = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            try:
                fn()
                print(f"PASS {name}")
            except Exception as e:
                failed += 1
                print(f"FAIL {name}: {e}")
    raise SystemExit(failed)
