#!/usr/bin/env python3
"""Break reference-v2 with the hardening pack. The 26 goldens are a separate lock."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ewp.fixtures import EVAL
from ewp.laundering import (
    PACK,
    claimed_independence,
    degraded_external_is_not_accepted,
    endogenous_check_does_not_refresh_external,
    episode_origin_is_not_trusted,
    honest_tool_same_lineage,
    human_attestation_on_extract,
    human_looks_right_vs_inspection,
    implied_conflict_without_row,
    incomplete_view_not_exhaustive,
    inconclusive_check_is_not_external,
    later_not_superseded,
    launder_repetition,
    launder_verification,
    mixed_timestamp_formats_use_instants,
    opposing_check_is_not_acceptance,
    scope_mismatch_is_not_external,
    customer_scope_mismatch,
    future_check_not_available_at_t,
    disjoint_subject_families_do_not_verify,
    cross_domain_subjects_do_not_verify,
    unsubjected_check_on_subjected_view,
    shared_subject_verifies,
    garbage_timestamp_is_not_available,
    unrelated_supersession_is_not_superseded,
    EVAL_AT,
)
from ewp.types import Policy
from ewp.warrant import warrant_now
from ewp.warrant_b import axes_only, naive_verification


POLICY = Policy()
AXES = ("acceptance", "conflict", "verification", "currency", "sufficiency")


def axes_a(view, evaluated_at=EVAL):
    w = warrant_now(view, POLICY, evaluated_at).warrant
    return {k: getattr(w, k) for k in AXES}


def test_self_verification_is_not_external():
    view = launder_verification()
    a = axes_a(view)
    b = axes_only(view, POLICY, EVAL)
    assert a["verification"] != "EXTERNAL", a
    assert b["verification"] != "EXTERNAL", b
    assert naive_verification(view) == "EXTERNAL"
    print("PASS self-verification: method-trusting naive=EXTERNAL; both evaluators != EXTERNAL")


def test_honest_tool_still_external():
    view = honest_tool_same_lineage()
    a = axes_a(view)
    assert a["verification"] == "EXTERNAL", a
    assert a["acceptance"] == "ACCEPTED", a
    print("PASS honest tool observation remains EXTERNAL")


def test_repetition_is_one_lineage():
    view = launder_repetition()
    w = warrant_now(view, POLICY, EVAL)
    assert w.independent_lineage_count == 1, w.independent_lineage_count
    print("PASS repetition laundering counts as 1 lineage")


def test_later_is_not_supersession():
    view = later_not_superseded()
    a = axes_a(view)
    assert a["currency"] != "SUPERSEDED", a
    print("PASS later observation is not supersession")


def test_incomplete_view_is_degraded():
    view = incomplete_view_not_exhaustive()
    a = axes_a(view)
    assert a["sufficiency"] == "DEGRADED", a
    print("PASS bounded view is DEGRADED, not a proof of absence")


def test_claimed_independence_is_two_claimed_lineages():
    view = claimed_independence()
    w = warrant_now(view, POLICY, EVAL)
    assert w.independent_lineage_count == 2
    assert view.adapter_meta.get("independence") == "claimed"
    print("PASS claimed independence remains a claim")


def test_human_class_is_the_same_quality_is_method():
    glance, inspect = human_looks_right_vs_inspection()
    assert axes_a(glance)["verification"] == "HUMAN"
    assert axes_a(inspect)["verification"] == "HUMAN"
    assert glance.checks[0].method != inspect.checks[0].method
    print("PASS HUMAN class shared; method/scope carry quality")



def test_opposing_check_opens_conflict_and_blocks_acceptance():
    view = opposing_check_is_not_acceptance()
    a = axes_a(view)
    assert a["verification"] == "EXTERNAL", a
    assert a["conflict"] == "OPEN", a
    assert a["acceptance"] != "ACCEPTED", a
    print("PASS opposing external check is EXTERNAL+OPEN, not ACCEPTED")


def test_inconclusive_cannot_be_external():
    view = inconclusive_check_is_not_external()
    a = axes_a(view)
    assert a["verification"] == "INDIRECT", a
    assert a["acceptance"] != "ACCEPTED", a
    print("PASS inconclusive tool check is INDIRECT, not EXTERNAL")


def test_human_method_on_extract_is_indirect():
    view = human_attestation_on_extract()
    a = axes_a(view)
    assert a["verification"] == "INDIRECT", a
    print("PASS human_attestation on extract is INDIRECT")


def test_implied_conflict_without_conflict_row():
    view = implied_conflict_without_row()
    a = axes_a(view)
    assert a["conflict"] == "OPEN", a
    assert a["acceptance"] != "ACCEPTED", a
    print("PASS opposing polarity implies OPEN without a Conflict row")


def test_endogenous_check_does_not_refresh_external_currency():
    view = endogenous_check_does_not_refresh_external()
    a = axes_a(view, evaluated_at="2026-09-21T21:00:00+00:00")
    assert a["verification"] == "EXTERNAL", a
    assert a["currency"] == "STALE", a
    assert a["acceptance"] != "ACCEPTED", a
    print("PASS later endogenous quote does not refresh EXTERNAL currency")


def test_episode_origin_is_not_external():
    a = axes_a(episode_origin_is_not_trusted())
    assert a["verification"] == "INDIRECT", a
    assert a["acceptance"] != "ACCEPTED", a
    print("PASS untrusted origin episode + document_quote is INDIRECT")


def test_degraded_external_is_tentative():
    a = axes_a(degraded_external_is_not_accepted())
    assert a["verification"] == "EXTERNAL", a
    assert a["sufficiency"] == "DEGRADED", a
    assert a["acceptance"] == "TENTATIVE", a
    print("PASS EXTERNAL + DEGRADED is TENTATIVE, not ACCEPTED")


def test_scope_mismatch_caps_class():
    a = axes_a(scope_mismatch_is_not_external())
    assert a["verification"] == "INDIRECT", a
    assert a["acceptance"] != "ACCEPTED", a
    print("PASS check scoped to server02 does not verify server01")



def test_customer_scope_mismatch_caps_class():
    a = axes_a(customer_scope_mismatch())
    assert a["verification"] == "INDIRECT", a
    assert a["acceptance"] != "ACCEPTED", a
    print("PASS check scoped to customer-99 does not verify customer-42")


def test_future_check_not_available_at_t():
    view = future_check_not_available_at_t()
    a = axes_a(view, evaluated_at="2026-09-21T10:00:00+00:00")
    assert a["verification"] != "EXTERNAL", a
    assert a["acceptance"] != "ACCEPTED", a
    print("PASS future-dated check cannot warrant acceptance at T")


def test_timestamp_formats_pick_later_instant():
    w = warrant_now(mixed_timestamp_formats_use_instants(), POLICY, EVAL)
    assert w.freshest_check == "k-z", w.freshest_check
    assert w.warrant.verification == "EXTERNAL"
    print("PASS Z vs offset timestamps compare as instants")

def test_subjects_are_exact_ids_not_families():
    for factory in (
        disjoint_subject_families_do_not_verify,
        cross_domain_subjects_do_not_verify,
        unsubjected_check_on_subjected_view,
    ):
        a = axes_a(factory())
        assert a["verification"] == "INDIRECT", (factory.__name__, a)
        assert a["acceptance"] == "TENTATIVE", (factory.__name__, a)
    a = axes_a(shared_subject_verifies())
    assert a["verification"] == "EXTERNAL", a
    assert a["acceptance"] == "ACCEPTED", a
    print("PASS subject binding: exact shared id verifies; other families and omitted subjects do not")


def test_garbage_timestamp_does_not_crash():
    w = warrant_now(garbage_timestamp_is_not_available(), POLICY, EVAL)
    assert w.warrant.verification == "NONE", w.warrant
    assert w.freshest_check is None, w.freshest_check
    print("PASS unparsable check time is unavailable at T and does not crash")


def test_unrelated_supersession_ignored():
    w = warrant_now(unrelated_supersession_is_not_superseded(), POLICY, EVAL)
    assert w.warrant.currency == "CURRENT", w.warrant
    assert w.superseded_by == [], w.superseded_by
    print("PASS superseded_by edge between other propositions does not supersede P")


def test_two_evaluators_match_on_axes():
    rows = []
    for name, factory in PACK:
        view = factory()
        when = EVAL_AT.get(name, EVAL)
        a = axes_a(view, evaluated_at=when)
        b = axes_only(view, POLICY, when)
        match = a == {k: b[k] for k in AXES}
        rows.append((name, a["verification"], b["verification"], match))
        assert match, (name, a, b)
    print("fixture                         A-verif     B-verif     match")
    print("--------------------------------------------------------------")
    for name, av, bv, match in rows:
        print(f"{name:32} {av:10} {bv:10} {'YES' if match else 'NO'}")
    print("PASS two evaluators agree on five axes for laundering pack")


def main() -> int:
    test_self_verification_is_not_external()
    test_honest_tool_still_external()
    test_repetition_is_one_lineage()
    test_later_is_not_supersession()
    test_incomplete_view_is_degraded()
    test_claimed_independence_is_two_claimed_lineages()
    test_human_class_is_the_same_quality_is_method()
    test_opposing_check_opens_conflict_and_blocks_acceptance()
    test_inconclusive_cannot_be_external()
    test_human_method_on_extract_is_indirect()
    test_implied_conflict_without_conflict_row()
    test_endogenous_check_does_not_refresh_external_currency()
    test_episode_origin_is_not_external()
    test_degraded_external_is_tentative()
    test_scope_mismatch_caps_class()
    test_customer_scope_mismatch_caps_class()
    test_future_check_not_available_at_t()
    test_timestamp_formats_pick_later_instant()
    test_subjects_are_exact_ids_not_families()
    test_garbage_timestamp_does_not_crash()
    test_unrelated_supersession_ignored()
    test_two_evaluators_match_on_axes()
    print("LAUNDERING SUITE PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
