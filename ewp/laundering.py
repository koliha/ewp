"""Hardening pack: epistemic-laundering and bounded-view fixtures.

These try to break reference-v2 without adding axes. Their expected axes
are pinned in docs/implementer/expected/, and this file is part of the
fixture-set hash in RELEASE.lock.json.
"""

from __future__ import annotations

from .fixtures import EVAL, assertion, ev, src
from .types import Conflict, EvidenceView, LineageEdge, VerificationCheck

T1 = "2026-09-21T18:31:00+00:00"
T_LATER = "2026-09-21T19:00:00+00:00"
T10 = "2026-09-21T10:00:00+00:00"
T11 = "2026-09-21T11:00:00+00:00"


def launder_repetition() -> EvidenceView:
    """A → A' → A'' on one lineage. Must count as one source."""
    root = src("a", "L1", "document")
    s1 = src("a1", "L1", "extract", parent="a")
    s2 = src("a2", "L1", "extract", parent="a1")
    return EvidenceView(
        "l-repeat",
        "P-x",
        assertions=[
            assertion("a0", "P-x", "X", root),
            assertion("a1", "P-x", "X", s1),
            assertion("a2", "P-x", "X", s2),
        ],
        evidence=[
            ev("e0", "P-x", "supports", root, "X"),
            ev("e1", "P-x", "supports", s1, "X"),
            ev("e2", "P-x", "supports", s2, "X"),
        ],
    )


def launder_summary() -> EvidenceView:
    """A → summary(A) presented as confirmation."""
    root = src("a", "L1", "document")
    summary = src("sum", "L1", "extract", parent="a")
    return EvidenceView(
        "l-summary",
        "P-x",
        assertions=[
            assertion("a0", "P-x", "X", root),
            assertion("a1", "P-x", "confirmed: X", summary),
        ],
        evidence=[
            ev("e0", "P-x", "supports", root, "X"),
            ev("e1", "P-x", "supports", summary, "summary of A"),
        ],
    )


def launder_verification() -> EvidenceView:
    """Assertion L1 → extract L1 → document_quote of the extract.

    Method string says EXTERNAL. Origin is endogenous. Must not be EXTERNAL.
    """
    root = src("a", "L1", "turn")
    derived = src("b", "L1", "extract", parent="a")
    return EvidenceView(
        "l-self-check",
        "P-healthy",
        assertions=[
            assertion("a0", "P-healthy", "The server is healthy.", root),
            assertion("a1", "P-healthy", "The server is healthy.", derived),
        ],
        evidence=[
            ev("e0", "P-healthy", "supports", root, "agent said healthy"),
            ev("e1", "P-healthy", "supports", derived, "summary of A"),
        ],
        lineage=[LineageEdge("b", "a", "derived_from")],
        checks=[
            VerificationCheck("k1", "document_quote", "summary of A", derived, T1, "supports"),
        ],
    )


def honest_tool_same_lineage() -> EvidenceView:
    """WinRM: assertion, evidence, and check share lineage and origin=tool.

    Same lineage is not laundering when the origin is the observation itself.
    """
    s = src("winrm", "L-obs", "tool")
    return EvidenceView(
        "l-honest-tool",
        "P-win",
        assertions=[assertion("a1", "P-win", "server01 runs Windows Server 2022", s)],
        evidence=[ev("e1", "P-win", "supports", s, "Get-ComputerInfo")],
        checks=[VerificationCheck("k1", "tool_observation", "server01", s, T1, "supports")],
        freshness_policy_seconds=86400 * 7,
    )


def later_not_superseded() -> EvidenceView:
    """B is later than A. That is not supersession without a lineage edge."""
    a = src("cam1", "L-a", "tool")
    b = src("cam2", "L-b", "tool")
    # observed_at on sources is T0 from helper; checks carry later time
    return EvidenceView(
        "l-later",
        "P-door",
        assertions=[
            assertion("a1", "P-door", "door is open", a),
            assertion("a2", "P-door", "door is open", b),
        ],
        evidence=[
            ev("e1", "P-door", "supports", a, "09:00"),
            ev("e2", "P-door", "supports", b, "10:00"),
        ],
        checks=[
            VerificationCheck("k1", "tool_observation", "door", a, T1, "supports"),
            VerificationCheck("k2", "tool_observation", "door", b, T_LATER, "supports"),
        ],
    )


def incomplete_view_not_exhaustive() -> EvidenceView:
    """Evaluator may not treat a bounded view as a proof of absence."""
    s1 = src("s1", "L1", "document")
    return EvidenceView(
        "l-incomplete",
        "P-x",
        assertions=[assertion("ax", "P-x", "X", s1)],
        evidence=[ev("ex", "P-x", "supports", s1, "X")],
        omitted_sources=["possible-contradictor"],
        retrieval_scope="topk",
        degraded=True,
    )


def claimed_independence() -> EvidenceView:
    """Two sources, two lineage_ids, no proof they are independent.

    EWP counts claimed lineages. It does not establish they are not syndicated.
    adapter_meta records the claim basis.
    """
    a, b = src("site-a", "L-a", "document"), src("site-b", "L-b", "document")
    return EvidenceView(
        "l-claimed",
        "P-x",
        assertions=[assertion("a1", "P-x", "X", a), assertion("a2", "P-x", "X", b)],
        evidence=[ev("e1", "P-x", "supports", a, "X"), ev("e2", "P-x", "supports", b, "X")],
        adapter_meta={"lineage_basis": "claimed_by_ingest", "independence": "claimed"},
    )


def human_looks_right_vs_inspection() -> tuple[EvidenceView, EvidenceView]:
    glance = src("dash", "L-h1", "human")
    inspect = src("chassis", "L-h2", "human")
    v_glance = EvidenceView(
        "l-human-glance",
        "P-serial",
        assertions=[assertion("a1", "P-serial", "serial is ABC", glance)],
        checks=[VerificationCheck("k1", "human_review", "dashboard_screenshot", glance, T1, "supports")],
    )
    v_inspect = EvidenceView(
        "l-human-inspect",
        "P-serial",
        assertions=[assertion("a1", "P-serial", "serial is ABC", inspect)],
        checks=[
            VerificationCheck("k1", "human_attestation", "physical_device_123", inspect, T1, "supports")
        ],
    )
    return v_glance, v_inspect



def opposing_check_is_not_acceptance() -> EvidenceView:
    """External check that opposes P. Verification can be EXTERNAL; acceptance cannot."""
    s = src("winrm", "L-obs", "tool")
    return EvidenceView(
        "l-oppose-check",
        "P-win",
        assertions=[assertion("a1", "P-win", "server01 runs Windows Server 2022", s)],
        evidence=[ev("e1", "P-win", "supports", s, "inventory row")],
        checks=[VerificationCheck("k1", "tool_observation", "server01", s, T1, "opposes")],
        freshness_policy_seconds=86400 * 7,
    )


def inconclusive_check_is_not_external() -> EvidenceView:
    s = src("probe", "L-obs", "tool")
    return EvidenceView(
        "l-inconclusive",
        "P-win",
        assertions=[assertion("a1", "P-win", "server01 runs Windows Server 2022", s)],
        evidence=[ev("e1", "P-win", "supports", s, "probe ran")],
        checks=[VerificationCheck("k1", "tool_observation", "server01", s, T1, "inconclusive")],
    )


def human_attestation_on_extract() -> EvidenceView:
    """human_attestation stamped on an extract must not raise HUMAN."""
    s = src("sum", "L1", "extract", parent="a")
    return EvidenceView(
        "l-human-extract",
        "P-x",
        assertions=[assertion("a1", "P-x", "X", s)],
        evidence=[ev("e1", "P-x", "supports", s, "summary")],
        checks=[VerificationCheck("k1", "human_attestation", "summary text", s, T1, "supports")],
    )


def implied_conflict_without_row() -> EvidenceView:
    """Supporting + opposing evidence, no Conflict object. Axis must still be OPEN."""
    a, b = src("cam1", "L-a", "tool"), src("cam2", "L-b", "tool")
    return EvidenceView(
        "l-implied",
        "P-door",
        assertions=[
            assertion("a1", "P-door", "door is open", a),
            assertion("a2", "P-door", "door is closed", b),
        ],
        evidence=[
            ev("e1", "P-door", "supports", a, "open"),
            ev("e2", "P-door", "opposes", b, "closed"),
        ],
        conflicts=[],
    )


def endogenous_check_does_not_refresh_external() -> EvidenceView:
    """Old external check + later endogenous quote. Currency follows the EXTERNAL check."""
    tool = src("winrm", "L-obs", "tool")
    extract = src("sum", "L-obs", "extract", parent="winrm")
    return EvidenceView(
        "l-stale-refresh",
        "P-win",
        assertions=[assertion("a1", "P-win", "server01 runs Windows Server 2022", tool)],
        evidence=[ev("e1", "P-win", "supports", tool, "Get-ComputerInfo")],
        checks=[
            VerificationCheck("k-old", "tool_observation", "server01", tool, "2026-06-01T00:00:00+00:00", "supports"),
            VerificationCheck("k-new", "document_quote", "summary", extract, T1, "supports"),
        ],
        freshness_policy_seconds=86400 * 7,
    )



def episode_origin_is_not_trusted() -> EvidenceView:
    """Graph-shaped origin 'episode' plus document_quote must not be EXTERNAL."""
    s = src("ep1", "L-g", "episode")
    return EvidenceView(
        "l-episode",
        "P-win",
        assertions=[assertion("a1", "P-win", "server01 runs Windows Server 2022", s)],
        evidence=[ev("e1", "P-win", "supports", s, "extracted fact")],
        checks=[VerificationCheck("k1", "document_quote", "server01", s, T1, "supports")],
    )


def degraded_external_is_not_accepted() -> EvidenceView:
    """A live tool check on an incomplete view is EXTERNAL + DEGRADED, not ACCEPTED."""
    s = src("winrm", "L-obs", "tool")
    return EvidenceView(
        "l-deg-ext",
        "P-win",
        assertions=[assertion("a1", "P-win", "server01 runs Windows Server 2022", s)],
        evidence=[ev("e1", "P-win", "supports", s, "Get-ComputerInfo")],
        checks=[VerificationCheck("k1", "tool_observation", "server01", s, T1, "supports")],
        omitted_sources=["possible-contradictor"],
        retrieval_scope="topk",
        degraded=True,
        freshness_policy_seconds=86400 * 7,
    )


def scope_mismatch_is_not_external() -> EvidenceView:
    """Check scoped to server02 cannot verify a server01 proposition."""
    s = src("winrm", "L-obs", "tool")
    return EvidenceView(
        "l-scope",
        "P-win",
        assertions=[assertion("a1", "P-win", "server01 runs Windows Server 2022", s)],
        evidence=[ev("e1", "P-win", "supports", s, "Get-ComputerInfo server01")],
        checks=[VerificationCheck("k1", "tool_observation", "server02", s, T1, "supports", subjects=("server02",))],
        subjects=("server01",),
        freshness_policy_seconds=86400 * 7,
    )



def customer_scope_mismatch() -> EvidenceView:
    """Check scoped to customer-99 cannot verify customer-42."""
    s = src("billing", "L-api", "api")
    return EvidenceView(
        "l-cust-scope",
        "P-refund",
        assertions=[assertion("a1", "P-refund", "customer-42 has approved the refund", s)],
        evidence=[ev("e1", "P-refund", "supports", s, "refund approved for customer-42")],
        checks=[VerificationCheck("k1", "external_api", "customer-99", s, T1, "supports", subjects=("customer-99",))],
        subjects=("customer-42",),
        freshness_policy_seconds=86400 * 7,
    )


def future_check_not_available_at_t() -> EvidenceView:
    """An 11:00 external check is not evidence available at 10:00."""
    s = src("api", "L-api", "api")
    return EvidenceView(
        "l-future-check",
        "P-refund",
        assertions=[assertion("a1", "P-refund", "customer-42 has approved the refund", s)],
        evidence=[ev("e1", "P-refund", "supports", s, "refund ticket")],
        checks=[VerificationCheck("k1", "external_api", "customer-42", s, T11, "supports")],
        freshness_policy_seconds=86400 * 7,
    )


def mixed_timestamp_formats_use_instants() -> EvidenceView:
    """Z vs +00:00 must not reorder freshest-check selection."""
    s = src("winrm", "L-obs", "tool")
    return EvidenceView(
        "l-tz",
        "P-win",
        assertions=[assertion("a1", "P-win", "server01 runs Windows Server 2022", s)],
        evidence=[ev("e1", "P-win", "supports", s, "Get-ComputerInfo")],
        checks=[
            VerificationCheck("k-z", "tool_observation", "server01", s, "2026-09-21T18:31:00Z", "supports"),
            VerificationCheck("k-off", "tool_observation", "server01", s, "2026-09-21T18:30:00+00:00", "supports"),
        ],
        freshness_policy_seconds=86400 * 7,
    )


def _refund_view(view_id: str, view_subjects: tuple[str, ...], check_subjects: tuple[str, ...]) -> EvidenceView:
    s = src("billing", "L-api", "api")
    return EvidenceView(
        view_id,
        "P-refund",
        assertions=[assertion("a1", "P-refund", "customer-42 has approved the refund", s)],
        evidence=[ev("e1", "P-refund", "supports", s, "refund approved for customer-42")],
        checks=[VerificationCheck("k1", "external_api", "billing lookup", s, T1, "supports", subjects=check_subjects)],
        subjects=view_subjects,
        freshness_policy_seconds=86400 * 7,
    )


def disjoint_subject_families_do_not_verify() -> EvidenceView:
    """customer-42 vs invoice-999: different families, still different subjects."""
    return _refund_view("l-subj-invoice", ("customer-42",), ("invoice-999",))


def cross_domain_subjects_do_not_verify() -> EvidenceView:
    """A check about customer-42 cannot verify a server01 proposition."""
    s = src("winrm", "L-obs", "tool")
    return EvidenceView(
        "l-subj-cross",
        "P-win",
        assertions=[assertion("a1", "P-win", "server01 runs Windows Server 2022", s)],
        evidence=[ev("e1", "P-win", "supports", s, "Get-ComputerInfo")],
        checks=[VerificationCheck("k1", "tool_observation", "inventory", s, T1, "supports", subjects=("customer-42",))],
        subjects=("server01",),
        freshness_policy_seconds=86400 * 7,
    )


def unsubjected_check_on_subjected_view() -> EvidenceView:
    """Omitting subjects on the check is not a way around the binding."""
    return _refund_view("l-subj-omitted", ("customer-42",), ())


def shared_subject_verifies() -> EvidenceView:
    """A multi-subject proposition is verified by a check on any declared subject."""
    return _refund_view("l-subj-shared", ("customer-42", "invoice-999"), ("invoice-999",))


def garbage_timestamp_is_not_available() -> EvidenceView:
    """An unparsable check time is not available at T. It must not crash."""
    s = src("winrm", "L-obs", "tool")
    return EvidenceView(
        "l-garbage-ts",
        "P-win",
        assertions=[assertion("a1", "P-win", "server01 runs Windows Server 2022", s)],
        evidence=[ev("e1", "P-win", "supports", s, "Get-ComputerInfo")],
        checks=[VerificationCheck("k1", "tool_observation", "server01", s, "garbage", "supports")],
        freshness_policy_seconds=86400 * 7,
    )


def unrelated_supersession_is_not_superseded() -> EvidenceView:
    """A superseded_by edge between other propositions does not supersede P."""
    s = src("winrm", "L-obs", "tool")
    return EvidenceView(
        "l-unrelated-sup",
        "P-win",
        assertions=[assertion("a1", "P-win", "server01 runs Windows Server 2022", s)],
        evidence=[ev("e1", "P-win", "supports", s, "Get-ComputerInfo")],
        checks=[VerificationCheck("k1", "tool_observation", "server01", s, T1, "supports")],
        lineage=[LineageEdge("P-unrelated-a", "P-unrelated-b", "superseded_by")],
        freshness_policy_seconds=86400 * 7,
    )


def zero_freshness_is_stale() -> EvidenceView:
    """freshness_policy_seconds=0 is a real value: a check one second old is stale."""
    s = src("winrm", "L-obs", "tool")
    return EvidenceView(
        "l-zero-fresh",
        "P-win",
        assertions=[assertion("a1", "P-win", "server01 runs Windows Server 2022", s)],
        evidence=[ev("e1", "P-win", "supports", s, "Get-ComputerInfo")],
        checks=[VerificationCheck("k1", "tool_observation", "server01", s, T1, "supports")],
        freshness_policy_seconds=0,
    )


PACK = [
    ("launder_repetition", launder_repetition),
    ("launder_summary", launder_summary),
    ("launder_verification", launder_verification),
    ("honest_tool_same_lineage", honest_tool_same_lineage),
    ("later_not_superseded", later_not_superseded),
    ("incomplete_view_not_exhaustive", incomplete_view_not_exhaustive),
    ("claimed_independence", claimed_independence),
    ("opposing_check_is_not_acceptance", opposing_check_is_not_acceptance),
    ("inconclusive_check_is_not_external", inconclusive_check_is_not_external),
    ("human_attestation_on_extract", human_attestation_on_extract),
    ("implied_conflict_without_row", implied_conflict_without_row),
    ("endogenous_check_does_not_refresh_external", endogenous_check_does_not_refresh_external),
    ("episode_origin_is_not_trusted", episode_origin_is_not_trusted),
    ("degraded_external_is_not_accepted", degraded_external_is_not_accepted),
    ("scope_mismatch_is_not_external", scope_mismatch_is_not_external),
    ("customer_scope_mismatch", customer_scope_mismatch),
    ("future_check_not_available_at_t", future_check_not_available_at_t),
    ("mixed_timestamp_formats_use_instants", mixed_timestamp_formats_use_instants),
    ("disjoint_subject_families_do_not_verify", disjoint_subject_families_do_not_verify),
    ("cross_domain_subjects_do_not_verify", cross_domain_subjects_do_not_verify),
    ("unsubjected_check_on_subjected_view", unsubjected_check_on_subjected_view),
    ("shared_subject_verifies", shared_subject_verifies),
    ("garbage_timestamp_is_not_available", garbage_timestamp_is_not_available),
    ("unrelated_supersession_is_not_superseded", unrelated_supersession_is_not_superseded),
    ("zero_freshness_is_stale", zero_freshness_is_stale),
]

EVAL_AT = {
    "future_check_not_available_at_t": T10,
    "zero_freshness_is_stale": "2026-09-21T18:31:01+00:00",
}


# Invalid pack: serialized views every conforming evaluator must refuse.
# Each is a valid view with exactly one defect, as the JSON a store or
# client would send.
def _base() -> dict:
    return honest_tool_same_lineage().to_dict()


def _customer() -> dict:
    return customer_scope_mismatch().to_dict()


def _mutated(make, change) -> dict:
    d = make()
    change(d)
    return d


INVALID_PACK = [
    ("cross_proposition_assertion", lambda: _mutated(_base, lambda d: d["assertions"][0].__setitem__("proposition_id", "P-other"))),
    ("cross_proposition_evidence", lambda: _mutated(_base, lambda d: d["evidence"][0].__setitem__("proposition_id", "P-other"))),
    ("unrelated_explicit_conflict", lambda: _mutated(_base, lambda d: d.__setitem__(
        "conflicts", [{"conflict_id": "c1", "proposition_ids": ["P-q", "P-r"], "status": "open", "note": ""}]))),
    ("string_subjects_on_view", lambda: _mutated(_customer, lambda d: d.__setitem__("subjects", "customer-42"))),
    ("string_subjects_on_check", lambda: _mutated(_customer, lambda d: d["checks"][0].__setitem__("subjects", "customer-99"))),
    ("negative_freshness", lambda: _mutated(_base, lambda d: d.__setitem__("freshness_policy_seconds", -5))),
    ("boolean_freshness", lambda: _mutated(_base, lambda d: d.__setitem__("freshness_policy_seconds", False))),
    ("string_degraded", lambda: _mutated(_base, lambda d: d.__setitem__("degraded", "false"))),
    ("unknown_check_result", lambda: _mutated(_base, lambda d: d["checks"][0].__setitem__("result", "pending"))),
    ("unknown_polarity", lambda: _mutated(_base, lambda d: d["evidence"][0].__setitem__("polarity", "oppose"))),
    ("unknown_conflict_status", lambda: _mutated(_base, lambda d: d.__setitem__(
        "conflicts", [{"conflict_id": "c1", "proposition_ids": ["P-win"], "status": "Open", "note": ""}]))),
    ("unknown_lineage_kind", lambda: _mutated(_base, lambda d: d.__setitem__(
        "lineage", [{"from_id": "P-win", "to_id": "P-next", "kind": "replaced_by"}]))),
    ("duplicate_assertion_id", lambda: _mutated(_base, lambda d: d["assertions"].append(
        dict(d["assertions"][0], text="server01 runs Windows Server 2019")))),
    ("duplicate_evidence_id", lambda: _mutated(_base, lambda d: d["evidence"].append(
        dict(d["evidence"][0], polarity="opposes")))),
    ("duplicate_check_id", lambda: _mutated(_base, lambda d: d["checks"].append(dict(d["checks"][0])))),
    ("duplicate_conflict_id", lambda: _mutated(_base, lambda d: d.__setitem__("conflicts", [
        {"conflict_id": "c1", "proposition_ids": ["P-win"], "status": "open", "note": ""},
        {"conflict_id": "c1", "proposition_ids": ["P-win"], "status": "resolved", "note": ""},
    ]))),
    ("conflicting_source_ref", lambda: _mutated(_base, lambda d: d["evidence"][0].__setitem__(
        "source", dict(d["evidence"][0]["source"], lineage_id="L-another")))),
    ("omitted_sources_string", lambda: _mutated(_base, lambda d: d.__setitem__("omitted_sources", "possible-contradictor"))),
    ("lineage_missing_endpoint", lambda: _mutated(_base, lambda d: d.__setitem__("lineage", [{"to_id": "P-next", "kind": "derived_from"}]))),
    ("conflict_participants_string", lambda: _mutated(_base, lambda d: d.__setitem__(
        "conflicts", [{"conflict_id": "c1", "proposition_ids": "P-win", "status": "open", "note": ""}]))),
    ("unparsable_evaluated_at", lambda: _mutated(_base, lambda d: d.__setitem__("evaluated_at", "not-a-time"))),
    ("missing_required_field", lambda: _mutated(_base, lambda d: d["evidence"][0].pop("content"))),
    ("non_numeric_confidence", lambda: _mutated(_base, lambda d: d["assertions"][0].__setitem__("assertion_confidence", "high"))),
]


__all__ = ["PACK", "INVALID_PACK", "EVAL", "human_looks_right_vs_inspection"]
