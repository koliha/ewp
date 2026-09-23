"""Four-stage Graphiti runner.

INGEST      → can the fixture be written without setting invalid_at?
RAW_VIEW    → can parked + raw edges reconstruct evidence?
WARRANT     → same epistemic payload as the in-memory reference?
SEARCH_VIEW → complete or explicitly DEGRADED?

Live graphiti-core is optional. Fake store is the semantic contract.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.runner import FIXTURES

# IDs assigned by the Graphiti edge mapper are not epistemic.
COMPARE_KEYS = (
    "warrant",
    "independent_lineage_count",
    "stale",
    "checks",
    "open_conflicts",
    "resolved_conflicts",
    "omitted_sources",
    "derived_from",
    "supersedes",
    "superseded_by",
    "freshest_check",
)
from ewp.fixtures import EVAL
from ewp.graphiti_adapter import GraphitiAdapter
from ewp.graphiti_ingest import ingest_view
from ewp.graphiti_records import FakeGraphitiStore
from ewp.types import Policy
from ewp.warrant import warrant_now

POLICY = Policy()


def _payload(view, evaluated_at):
    return warrant_now(view, POLICY, evaluated_at).normalized()


def _diff(expected, actual):
    lines = []
    for key in COMPARE_KEYS:
        if expected.get(key) != actual.get(key):
            lines.append(f"  {key}\n    expected: {expected.get(key)!r}\n    actual:   {actual.get(key)!r}")
    return lines


def classify(ingest_ok, raw_ok, warrant_ok, search_ok, search_degraded_ok):
    if not ingest_ok:
        return "INGEST_LOSS"
    if not raw_ok:
        return "ADAPTER_MAP_LOSS"
    if not warrant_ok:
        return "WARRANT_MISMATCH"
    if not search_ok and not search_degraded_ok:
        return "RETRIEVAL_LOSS"
    if not search_ok and search_degraded_ok:
        return "RETRIEVAL_LOSS_MARKED"
    return "PASS"


def run() -> int:
    failed = 0
    for name, cases in FIXTURES:
        _pid, view, evaluated_at = cases[0]
        reference = _payload(view, evaluated_at)
        fact = view.assertions[0].text if view.assertions else view.proposition_id

        store = FakeGraphitiStore()
        report = ingest_view(store, view)
        ingest_ok = report["invalid_at_written"] is False
        ingest_ok = ingest_ok and report["episodes"] >= 0

        adapter = GraphitiAdapter(store)
        raw = adapter.raw_view(view.proposition_id, fact)
        raw_ok = True
        if view.conflicts and not raw.conflicts:
            raw_ok = False
        if view.checks and not raw.checks:
            raw_ok = False

        got = _payload(raw, evaluated_at)
        warrant_delta = _diff(reference, got)
        warrant_ok = not warrant_delta

        # retrieval: if we don't register search hits, search is empty → must be DEGRADED
        store.search_hits[fact] = []
        search = adapter.search_view(view.proposition_id, fact, fact)
        search_w = _payload(search, evaluated_at)
        search_complete = not _diff(reference, search_w)
        search_degraded_ok = (
            search_w["warrant"]["sufficiency"] == "DEGRADED" or search_complete
        )
        # empty search of a non-empty raw store is retrieval loss; must be degraded
        if store.raw_edges(fact) and not store.search(fact):
            search_ok = False
            search_degraded_ok = search_w["warrant"]["sufficiency"] == "DEGRADED"
        else:
            search_ok = search_complete

        tag = classify(ingest_ok, raw_ok, warrant_ok, search_ok, search_degraded_ok)
        if tag not in {"PASS", "RETRIEVAL_LOSS_MARKED"}:
            failed += 1
        print(f"\nfixture: {name}")
        print(f"INGEST:       {'PASS' if ingest_ok else 'FAIL'}")
        print(f"RAW_VIEW:     {'PASS' if raw_ok else 'FAIL'}")
        print(f"WARRANT:      {'PASS' if warrant_ok else 'FAIL'}")
        print(f"SEARCH_VIEW:  {'PASS' if search_ok else ('DEGRADED' if search_degraded_ok else 'FAIL')}")
        print(f"classification: {tag}")
        if warrant_delta:
            print("difference:")
            print("\n".join(warrant_delta))
    print(f"\n{failed} unclassified-or-hard failures")
    return failed


if __name__ == "__main__":
    raise SystemExit(run())
