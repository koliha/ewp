"""Cross-adapter conformance runner.

Compares only normalized WarrantView epistemic payload.
Prints field-level diffs so an adapter author can see *what* leaked.
"""

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
from ewp.json_adapter import JsonFileAdapter
from ewp.sqlite_adapter import SQLiteAdapter
from ewp.types import EvidenceView, Policy
from ewp.warrant import warrant_now

POLICY = Policy()
COMPARE_KEYS = (
    "warrant",
    "independent_lineage_count",
    "stale",
    "checks",
    "supporting_evidence_ids",
    "opposing_evidence_ids",
    "open_conflicts",
    "resolved_conflicts",
    "omitted_sources",
    "derived_from",
    "supersedes",
    "superseded_by",
    "freshest_check",
)


def _load_through(adapter_cls, view: EvidenceView) -> EvidenceView:
    if adapter_cls is SQLiteAdapter:
        ad = adapter_cls()
        ad.load_view(view)
        return ad.get_view(view.proposition_id, view.view_id)
    tmp = TemporaryDirectory()
    ad = adapter_cls(tmp.name)
    ad.load_view(view)
    loaded = ad.get_view(view.proposition_id, view.view_id)
    # keep tmp alive for the call; then persist loaded which is already in memory
    tmp.cleanup()
    return loaded


def _payload(view: EvidenceView, evaluated_at: str) -> dict:
    return warrant_now(view, POLICY, evaluated_at).normalized()


def _diff(expected: dict, actual: dict) -> list[str]:
    lines = []
    for key in COMPARE_KEYS:
        if expected.get(key) != actual.get(key):
            lines.append(f"  {key}\n    expected: {expected.get(key)!r}\n    actual:   {actual.get(key)!r}")
    return lines


FIXTURES: list[tuple[str, list[tuple[str, EvidenceView, str]]]] = [
    ("01-reinforcement", [("P-x", fixture_reinforcement(), EVAL)]),
    ("02-fork-x", [("P-x", fixture_fork()[0], EVAL)]),
    ("02-fork-not-x", [("P-not-x", fixture_fork()[1], EVAL)]),
    ("03-compression-full", [("P-x", fixture_compression_full(), EVAL)]),
    ("03-compression-honest", [("P-x", fixture_compression_honest(), EVAL)]),
    ("04-retrieval-complete", [("P-x", fixture_retrieval_complete(), EVAL)]),
    ("04-retrieval-degraded", [("P-x", fixture_retrieval_degraded(), EVAL)]),
    ("05-persona", [("P-checked", fixture_persona(), EVAL)]),
    ("06-premises", [("P-occ", fixture_premises_tentative(), EVAL)]),
    ("06-derived", [("P-hvac", fixture_derived(), EVAL)]),
    ("07-lineage", [("P-x", fixture_lineage_clones(), EVAL)]),
    ("08-verified-now", [("P-win", fixture_verified_current(), EVAL)]),
    ("08-verified-stale", [("P-win", fixture_verified_current(), EVAL_LATE)]),
    ("08-superseded", [("P-old", fixture_superseded(), EVAL)]),
]


def run() -> int:
    from ewp.graphiti_live import runtime_version
    from ewp.versions import banner

    print(banner(runtime_version()))
    adapters = [("SQLite", SQLiteAdapter), ("JSON", JsonFileAdapter)]
    failed = 0
    for name, cases in FIXTURES:
        print(f"\n{name}")
        ref_view, eval_at = cases[0][1], cases[0][2]
        reference = _payload(ref_view, eval_at)
        for label, cls in adapters:
            loaded = _load_through(cls, ref_view)
            got = _payload(loaded, eval_at)
            delta = _diff(reference, got)
            if delta:
                failed += 1
                print(f"{label}: FAIL")
                print("difference:")
                print("\n".join(delta))
            else:
                print(f"{label}: PASS")
    print(f"\n{failed} adapter/fixture failures")
    return failed


if __name__ == "__main__":
    raise SystemExit(run())
