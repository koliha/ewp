"""Apply Graphiti-like local reconciliation *after* ingest.

These mutations are store-local. warrant_now must ignore them except
as notes the adapter is required to explain.
"""

from __future__ import annotations

from .graphiti_records import FakeGraphitiStore


def apply_hostile(name: str, store: FakeGraphitiStore) -> dict:
    """Mutate the fake graph. Return store_projection for EXPECTED_DIVERGENCE."""
    proj: dict = {"current_facts": [], "invalidated": [], "search_kept": []}
    edges = list(store.edges.values())

    def invalidate(edge_uuid: str, reason: str) -> None:
        e = store.edges[edge_uuid]
        e.invalid_at = "2026-09-21T20:00:00+00:00"
        e.expired_at = e.invalid_at
        proj["invalidated"].append({"uuid": edge_uuid, "fact": e.fact, "reason": reason})

    if name == "p1-false-supersession" and edges:
        invalidate(edges[0].uuid, "semantically similar to server02/2022")
        proj["current_facts"] = ["server02 runs Server 2022"]

    elif name == "p2-contradiction-open":
        for e in edges:
            if "open" in e.fact:
                invalidate(e.uuid, "contradicted by closed")
        proj["current_facts"] = ["door is closed"]

    elif name == "p3-real-upgrade":
        for e in edges:
            if "2019" in e.fact:
                invalidate(e.uuid, "later 2022 fact")
        proj["current_facts"] = ["server01 runs Server 2022"]

    elif name == "p4-same-text-independent":
        if edges:
            store.search_hits["X"] = [edges[0].uuid]
            proj["search_kept"] = [edges[0].uuid]
            proj["current_facts"] = [edges[0].fact]

    elif name == "p5-diff-text-one-lineage":
        proj["current_facts"] = [e.fact for e in edges]

    elif name == "p6-current-vs-verified":
        for e in edges:
            if "2019" in e.fact:
                invalidate(e.uuid, "chose 2022 as current")
        proj["current_facts"] = ["server01 runs Server 2022"]

    elif name == "p7-weak-vs-strong":
        for e in edges:
            if e.fact == "X":
                invalidate(e.uuid, "weak not-X nominated contradiction")
        proj["current_facts"] = ["not X"]

    elif name == "p8-verify-survives-expiry":
        for e in edges:
            invalidate(e.uuid, "maintenance expired canonical edge")
        proj["current_facts"] = []

    elif name == "p9-false-consensus":
        keep = [e.uuid for e in edges if e.fact == "X"]
        store.search_hits["X"] = keep
        store.search_hits["P-x"] = keep
        proj["search_kept"] = keep
        proj["current_facts"] = ["X"]

    elif name == "p10-same-lineage-conflict":
        proj["current_facts"] = [e.fact for e in edges]

    elif name == "p11-maintenance-no-verify":
        for e in edges:
            e.expired_at = None  # "canonical/current"
        proj["current_facts"] = ["X"]

    elif name == "p12-invalidation-cycle":
        if len(edges) >= 3:
            invalidate(edges[0].uuid, "A invalidated by B")
            invalidate(edges[1].uuid, "B invalidated by C")
            # C conflicts with A; Graphiti has no unique survivor
        proj["current_facts"] = []

    return proj
