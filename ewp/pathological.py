"""Fixtures that make Graphiti-style local reconciliation disagree with warrant_now.

Store-local reconciliation may change what the adapter must explain.
It must not change what counts as warrant.
"""

from __future__ import annotations

from .fixtures import src, assertion, ev, T0, T1
from .types import (
    Conflict,
    EvidenceView,
    LineageEdge,
    VerificationCheck,
)

T2 = "2026-09-21T19:00:00+00:00"


def p1_false_supersession() -> EvidenceView:
    a = src("s-a", "L-2019", "tool")
    b = src("s-b", "L-2022", "tool")
    return EvidenceView(
        "p1",
        "P-server01-2019",
        assertions=[assertion("a1", "P-server01-2019", "server01 runs Server 2019", a)],
        evidence=[ev("e1", "P-server01-2019", "supports", a, "2019")],
        lineage=[],
        adapter_meta={"sibling_fact": "server02 runs Server 2022", "sibling_source": b.__dict__},
    )


def p2_contradiction_no_supersession() -> EvidenceView:
    a, b = src("s-open", "L-cam1"), src("s-shut", "L-cam2")
    return EvidenceView(
        "p2",
        "P-door",
        assertions=[
            assertion("a1", "P-door", "door is open", a),
            assertion("a2", "P-door", "door is closed", b),
        ],
        evidence=[
            ev("e1", "P-door", "supports", a, "open"),
            ev("e2", "P-door", "opposes", b, "closed"),
        ],
        conflicts=[Conflict("c-door", ("P-door",), "open")],
    )


def p3_real_temporal_upgrade() -> EvidenceView:
    a, b = src("s1", "L-inv", "tool"), src("s2", "L-inv", "tool")
    return EvidenceView(
        "p3",
        "P-server01-os",
        assertions=[
            assertion("a1", "P-server01-os", "server01 runs Server 2019", a),
            assertion("a2", "P-server01-os", "server01 runs Server 2022", b),
        ],
        evidence=[
            ev("e1", "P-server01-os", "supports", a, "inventory T1"),
            ev("e2", "P-server01-os", "supports", b, "inventory T2 after upgrade"),
        ],
        lineage=[
            LineageEdge("P-server01-os:2019", "P-server01-os:2022", "superseded_by"),
            LineageEdge("P-server01-os:2022", "P-server01-os:2019", "supersedes"),
        ],
        checks=[
            VerificationCheck("k2", "tool_observation", "server01", b, T2, "supports"),
        ],
    )


def p4_same_text_independent() -> EvidenceView:
    a, b = src("epA", "L-alpha"), src("epB", "L-beta")
    return EvidenceView(
        "p4",
        "P-x",
        assertions=[
            assertion("a1", "P-x", "X", a),
            assertion("a2", "P-x", "X", b),
        ],
        evidence=[ev("e1", "P-x", "supports", a, "X"), ev("e2", "P-x", "supports", b, "X")],
    )


def p5_different_text_same_lineage() -> EvidenceView:
    root = src("reuters", "L-reut", "document")
    blog = src("blog", "L-reut", "extract", parent="reuters")
    agent = src("agent", "L-reut", "extract", parent="blog")
    return EvidenceView(
        "p5",
        "P-x",
        assertions=[
            assertion("a1", "P-x", "Pluto is a dwarf planet", root),
            assertion("a2", "P-x", "IAU reclassified Pluto", blog),
            assertion("a3", "P-x", "Pluto no longer counts as a planet", agent),
        ],
        evidence=[
            ev("e1", "P-x", "supports", root, "IAU 2006"),
            ev("e2", "P-x", "supports", blog, "summary"),
            ev("e3", "P-x", "supports", agent, "paraphrase"),
        ],
    )


def p6_current_vs_verified() -> EvidenceView:
    a = src("winrm", "L-obs", "tool")
    b = src("chat", "L-talk", "turn")
    return EvidenceView(
        "p6",
        "P-os",
        assertions=[
            assertion("a1", "P-os", "server01 runs Server 2019", a),
            assertion("a2", "P-os", "server01 runs Server 2022", b, 0.95),
        ],
        evidence=[
            ev("e1", "P-os", "supports", a, "WinRM"),
            ev("e2", "P-os", "supports", b, "someone said 2022"),
        ],
        conflicts=[Conflict("c-os", ("P-os",), "open")],
        checks=[VerificationCheck("k1", "tool_observation", "server01", a, T1, "supports")],
    )


def p7_weak_invalidates_strong() -> EvidenceView:
    a, b = src("s-strong", "L-doc", "document"), src("s-weak", "L-rumor", "turn")
    return EvidenceView(
        "p7",
        "P-x",
        assertions=[
            assertion("a1", "P-x", "X", a, 0.9),
            assertion("a2", "P-x", "not X", b, 0.2),
        ],
        evidence=[
            ev("e1", "P-x", "supports", a, "spec"),
            ev("e2", "P-x", "opposes", b, "maybe not"),
        ],
        conflicts=[Conflict("c1", ("P-x",), "open")],
        checks=[VerificationCheck("k1", "document_quote", "spec p.12", a, T1, "supports")],
    )


def p8_verification_survives_expiry() -> EvidenceView:
    a = src("winrm", "L-obs", "tool")
    return EvidenceView(
        "p8",
        "P-win",
        assertions=[assertion("a1", "P-win", "server01 runs Windows Server 2022", a)],
        evidence=[ev("e1", "P-win", "supports", a, "Get-ComputerInfo")],
        checks=[VerificationCheck("k1", "tool_observation", "server01", a, T1, "supports")],
        freshness_policy_seconds=86400 * 365,
    )


def p9_retrieval_false_consensus() -> EvidenceView:
    a, b, n = src("sA", "LA"), src("sB", "LB"), src("sN", "LN")
    return EvidenceView(
        "p9",
        "P-x",
        assertions=[
            assertion("a1", "P-x", "X", a),
            assertion("a2", "P-x", "not X", b),
        ],
        evidence=[
            ev("e1", "P-x", "supports", a, "X"),
            ev("e2", "P-x", "opposes", b, "not X"),
            ev("e3", "P-x", "supports", n, "unclear"),
        ],
        conflicts=[Conflict("c1", ("P-x",), "open")],
    )


def p10_duplicate_contradiction_same_lineage() -> EvidenceView:
    root = src("reuters", "L-reut")
    bad = src("extract-err", "L-reut", "extract", parent="reuters")
    return EvidenceView(
        "p10",
        "P-x",
        assertions=[
            assertion("a1", "P-x", "X", root),
            assertion("a2", "P-x", "not X", bad),
        ],
        evidence=[
            ev("e1", "P-x", "supports", root, "X"),
            ev("e2", "P-x", "opposes", bad, "not X"),
        ],
        conflicts=[Conflict("c1", ("P-x",), "open")],
    )


def p11_maintenance_no_verify() -> EvidenceView:
    a = src("s1", "L1", "turn")
    return EvidenceView(
        "p11",
        "P-x",
        assertions=[assertion("a1", "P-x", "X", a)],
        evidence=[ev("e1", "P-x", "supports", a, "said X")],
    )


def p12_invalidation_cycle() -> EvidenceView:
    a, b, c = src("sa", "LA"), src("sb", "LB"), src("sc", "LC")
    return EvidenceView(
        "p12",
        "P-cycle",
        assertions=[
            assertion("a1", "P-cycle", "A", a),
            assertion("a2", "P-cycle", "B", b),
            assertion("a3", "P-cycle", "C", c),
        ],
        evidence=[
            ev("e1", "P-cycle", "supports", a, "A"),
            ev("e2", "P-cycle", "supports", b, "B"),
            ev("e3", "P-cycle", "supports", c, "C"),
        ],
        conflicts=[Conflict("c-cycle", ("P-cycle",), "open")],
    )


PACK = [
    ("p1-false-supersession", p1_false_supersession),
    ("p2-contradiction-open", p2_contradiction_no_supersession),
    ("p3-real-upgrade", p3_real_temporal_upgrade),
    ("p4-same-text-independent", p4_same_text_independent),
    ("p5-diff-text-one-lineage", p5_different_text_same_lineage),
    ("p6-current-vs-verified", p6_current_vs_verified),
    ("p7-weak-vs-strong", p7_weak_invalidates_strong),
    ("p8-verify-survives-expiry", p8_verification_survives_expiry),
    ("p9-false-consensus", p9_retrieval_false_consensus),
    ("p10-same-lineage-conflict", p10_duplicate_contradiction_same_lineage),
    ("p11-maintenance-no-verify", p11_maintenance_no_verify),
    ("p12-invalidation-cycle", p12_invalidation_cycle),
]
