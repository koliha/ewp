"""Canonical evidence bundles for the v0.1 conformance suite."""

from __future__ import annotations

from .types import (
    Assertion,
    Conflict,
    EvidenceItem,
    EvidenceView,
    LineageEdge,
    SourceRef,
    VerificationCheck,
)

T0 = "2026-09-01T00:00:00+00:00"
T1 = "2026-09-21T18:31:00+00:00"
EVAL = "2026-09-21T21:00:00+00:00"
EVAL_LATE = "2026-12-01T00:00:00+00:00"


def src(sid: str, lineage: str, kind: str = "document", parent: str | None = None) -> SourceRef:
    return SourceRef(
        source_id=sid,
        lineage_id=lineage,
        origin_type=kind,
        origin_locator=f"loc:{sid}",
        snapshot_id=f"snap:{sid}",
        content_hash=f"sha256:{sid}",
        observed_at=T0,
        parent_source_id=parent,
    )


def assertion(aid: str, pid: str, text: str, source: SourceRef, conf: float = 0.9) -> Assertion:
    return Assertion(aid, pid, text, "agent", conf, source, T0)


def ev(eid: str, pid: str, polarity: str, source: SourceRef, content: str) -> EvidenceItem:
    return EvidenceItem(eid, pid, polarity, source, content, T0)  # type: ignore[arg-type]


def fixture_reinforcement() -> EvidenceView:
    s = src("s1", "L-reut")
    assertions = [
        assertion(f"a{i}", "P-x", "X", s, 0.99) for i in range(100)
    ]
    return EvidenceView("v-reinforce", "P-x", assertions=assertions, evidence=[ev("e1", "P-x", "supports", s, "X")])


def fixture_fork() -> tuple[EvidenceView, EvidenceView]:
    sx = src("sx", "L-b")
    sn = src("sn", "L-c")
    vx = EvidenceView(
        "v-fork-x",
        "P-x",
        assertions=[assertion("ax", "P-x", "X", sx)],
        evidence=[ev("ex", "P-x", "supports", sx, "X")],
        conflicts=[Conflict("c1", ("P-x", "P-not-x"), "open")],
    )
    vn = EvidenceView(
        "v-fork-n",
        "P-not-x",
        assertions=[assertion("an", "P-not-x", "not X", sn)],
        evidence=[ev("en", "P-not-x", "supports", sn, "not X")],
        conflicts=[Conflict("c1", ("P-x", "P-not-x"), "open")],
    )
    return vx, vn


def fixture_compression_full() -> EvidenceView:
    s1, s2 = src("s1", "L1"), src("s2", "L2")
    return EvidenceView(
        "v-comp-full",
        "P-x",
        assertions=[assertion("ax", "P-x", "X", s1), assertion("an", "P-x", "not X", s2)],
        evidence=[ev("ex", "P-x", "supports", s1, "X"), ev("en", "P-x", "opposes", s2, "not X")],
        conflicts=[Conflict("c1", ("P-x",), "open")],
    )


def fixture_compression_dropped_opposition() -> EvidenceView:
    """Illegal compression: opposition omitted without degraded flag."""
    s1 = src("s1", "L1")
    return EvidenceView(
        "v-comp-bad",
        "P-x",
        assertions=[assertion("ax", "P-x", "X", s1)],
        evidence=[ev("ex", "P-x", "supports", s1, "X")],
        omitted_sources=["s2"],
        retrieval_scope="compressed",
        degraded=False,  # adapter bug if this happens
    )


def fixture_compression_honest() -> EvidenceView:
    s1 = src("s1", "L1")
    return EvidenceView(
        "v-comp-ok",
        "P-x",
        assertions=[assertion("ax", "P-x", "X", s1)],
        evidence=[ev("ex", "P-x", "supports", s1, "X")],
        omitted_sources=["s2"],
        retrieval_scope="compressed",
        degraded=True,
    )


def fixture_retrieval_complete() -> EvidenceView:
    s1, s2 = src("s1", "L1"), src("s2", "L2")
    return EvidenceView(
        "v-ret-ok",
        "P-x",
        assertions=[assertion("ax", "P-x", "X", s1)],
        evidence=[ev("ex", "P-x", "supports", s1, "X"), ev("en", "P-x", "opposes", s2, "not X")],
        conflicts=[Conflict("c1", ("P-x",), "open")],
        retrieval_scope="complete",
    )


def fixture_retrieval_degraded() -> EvidenceView:
    s1 = src("s1", "L1")
    return EvidenceView(
        "v-ret-deg",
        "P-x",
        assertions=[assertion("ax", "P-x", "X", s1)],
        evidence=[ev("ex", "P-x", "supports", s1, "X")],
        omitted_sources=["s2"],
        retrieval_scope="topk",
        degraded=True,
    )


def fixture_persona() -> EvidenceView:
    s = src("sp", "L-self", kind="turn")
    return EvidenceView(
        "v-persona",
        "P-checked",
        assertions=[assertion("a1", "P-checked", "I checked this yesterday", s, 0.99)],
    )


def fixture_premises_tentative() -> EvidenceView:
    s = src("s1", "L1", kind="turn")
    return EvidenceView(
        "v-prem",
        "P-occ",
        assertions=[assertion("a1", "P-occ", "building is occupied", s)],
        evidence=[ev("e1", "P-occ", "supports", s, "someone said occupied")],
        lineage=[LineageEdge("P-hvac", "P-occ", "derived_from")],
    )


def fixture_derived() -> EvidenceView:
    s = src("s1", "L1", kind="turn")
    return EvidenceView(
        "v-derived",
        "P-hvac",
        assertions=[assertion("a2", "P-hvac", "HVAC is required", s)],
        evidence=[ev("e2", "P-hvac", "supports", s, "inferred from occupancy")],
        lineage=[LineageEdge("P-hvac", "P-occ", "derived_from")],
        checks=[
            # illegal if someone stamps EXTERNAL on the conclusion alone
        ],
    )


def fixture_lineage_clones() -> EvidenceView:
    root = src("reuters", "L-reut", kind="document")
    blog = src("blog", "L-reut", kind="extract", parent="reuters")
    agent = src("agent", "L-reut", kind="extract", parent="blog")
    quote = src("quote", "L-reut", kind="turn", parent="agent")
    return EvidenceView(
        "v-clone",
        "P-x",
        assertions=[
            assertion("a1", "P-x", "X", root),
            assertion("a2", "P-x", "X", blog),
            assertion("a3", "P-x", "X", agent),
            assertion("a4", "P-x", "X", quote),
        ],
        evidence=[
            ev("e1", "P-x", "supports", root, "X"),
            ev("e2", "P-x", "supports", blog, "X"),
            ev("e3", "P-x", "supports", agent, "X"),
            ev("e4", "P-x", "supports", quote, "X"),
        ],
    )


def fixture_verified_current() -> EvidenceView:
    s = src("winrm", "L-obs", kind="tool")
    return EvidenceView(
        "v-ver",
        "P-win",
        assertions=[assertion("a1", "P-win", "server01 runs Windows Server 2022", s)],
        evidence=[ev("e1", "P-win", "supports", s, "Get-ComputerInfo")],
        checks=[
            VerificationCheck(
                "k1",
                "tool_observation",
                "server01",
                s,
                T1,
                "supports",
            )
        ],
        freshness_policy_seconds=86400 * 7,
    )


def fixture_superseded() -> EvidenceView:
    s = src("s1", "L1")
    return EvidenceView(
        "v-sup",
        "P-old",
        assertions=[assertion("a1", "P-old", "Pluto is a planet", s)],
        evidence=[ev("e1", "P-old", "supports", s, "old textbook")],
        lineage=[LineageEdge("P-old", "P-new", "superseded_by")],
    )
