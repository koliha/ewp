"""Print store vs warrant projections. Divergence is expected, not a failure."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ewp.fixtures import EVAL
from ewp.graphiti_adapter import GraphitiAdapter
from ewp.graphiti_hostile import apply_hostile
from ewp.graphiti_ingest import ingest_view
from ewp.graphiti_records import FakeGraphitiStore
from ewp.pathological import PACK
from ewp.types import Policy
from ewp.warrant import warrant_now

POLICY = Policy()


def main() -> int:
    for name, factory in PACK:
        view = factory()
        store = FakeGraphitiStore()
        ingest_view(store, view)
        proj = apply_hostile(name, store)
        raw = GraphitiAdapter(store).raw_view(view.proposition_id)
        w = warrant_now(raw, POLICY, EVAL).warrant
        store_says = proj.get("current_facts") or ["(none)"]
        print(f"\n{name}")
        print(f"  store_projection:  {store_says}")
        print(f"  invalidated:       {len(proj.get('invalidated') or [])}")
        print(
            f"  warrant_projection: acceptance={w.acceptance} conflict={w.conflict} "
            f"verification={w.verification} currency={w.currency} sufficiency={w.sufficiency}"
        )
        disagrees = bool(proj.get("invalidated") or proj.get("search_kept")) and (
            w.currency != "SUPERSEDED" or w.conflict == "OPEN" or w.verification in {"EXTERNAL", "HUMAN"}
        )
        print(f"  status: {'EXPECTED_DIVERGENCE' if disagrees else 'ALIGNED_OR_NEUTRAL'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
