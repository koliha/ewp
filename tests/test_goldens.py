"""Goldens are the protocol. Stores do not get to rewrite them."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ewp.fixtures import EVAL
from ewp.pathological import PACK
from ewp.types import Policy
from ewp.warrant import warrant_now
from tests.runner import FIXTURES

GOLDEN = Path(__file__).resolve().parent / "golden_warrantviews"
POLICY = Policy()


def test_canonical_goldens():
    for name, cases in FIXTURES:
        _pid, view, evaluated_at = cases[0]
        got = warrant_now(view, POLICY, evaluated_at).normalized()
        expected = json.loads((GOLDEN / f"{name}.json").read_text())
        got["warrant"].pop("strength", None)
        expected["warrant"].pop("strength", None)
        assert got == expected, name


def test_pathological_goldens():
    for name, factory in PACK:
        got = warrant_now(factory(), POLICY, EVAL).normalized()
        expected = json.loads((GOLDEN / f"{name}.json").read_text())
        got["warrant"].pop("strength", None)
        expected["warrant"].pop("strength", None)
        assert got == expected, name


def test_implementer_pack_matches_reference():
    """Every fixture in docs/implementer (canonical, pathological, hardening)
    has expected axes equal to the reference evaluator's, under this identity."""
    from ewp.codec import view_from_dict
    from ewp.versions import PROTOCOL

    pack = Path(__file__).resolve().parents[1] / "docs" / "implementer"
    fixtures = sorted((pack / "fixtures").glob("*.json"))
    from ewp.laundering import PACK as HARDENING
    from ewp.pathological import PACK as PATHOLOGICAL

    assert len(fixtures) == len(FIXTURES) + len(PATHOLOGICAL) + len(HARDENING), len(fixtures)
    for path in fixtures:
        raw = json.loads(path.read_text(encoding="utf-8"))
        expected = json.loads((pack / "expected" / path.name).read_text(encoding="utf-8"))
        got = warrant_now(view_from_dict(raw), POLICY, raw["evaluated_at"]).normative()
        assert expected["protocol_version"] == PROTOCOL == got["protocol_version"], path.name
        assert expected["policy_version"] == POLICY.version == got["policy_version"], path.name
        for axis in ("acceptance", "conflict", "verification", "currency", "sufficiency"):
            assert got["warrant"][axis] == expected[axis], (path.name, axis)


def test_invalid_pack_is_refused():
    """docs/implementer/invalid: the reference codec and evaluator refuse every one."""
    from ewp.codec import view_from_dict
    from ewp.laundering import INVALID_PACK

    pack = Path(__file__).resolve().parents[1] / "docs" / "implementer" / "invalid"
    files = sorted(pack.glob("*.json"))
    assert len(files) == len(INVALID_PACK), (len(files), len(INVALID_PACK))
    for path in files:
        raw = json.loads(path.read_text(encoding="utf-8"))
        try:
            warrant_now(view_from_dict(raw), POLICY, raw["evaluated_at"])
        except ValueError:  # InvalidEvidenceView, or an unparsable evaluated_at
            continue
        raise AssertionError(f"{path.name} was accepted")


def _json_variants(raw: dict) -> list[tuple[str, dict]]:
    """Same view, different but schema-equivalent JSON spellings."""
    import copy

    defaults = {"retrieval_scope": "complete", "degraded": False, "freshness_policy_seconds": 86400 * 30,
                "omitted_sources": [], "subjects": []}
    nulled = copy.deepcopy(raw)
    for key, default in defaults.items():
        if nulled.get(key) == default:
            nulled[key] = None
    sparse = copy.deepcopy(raw)
    for part in ("assertions", "evidence", "checks"):
        for record in sparse[part]:
            if record.get("proposition_id") == sparse["proposition_id"]:
                record.pop("proposition_id")
            for key in ("extractor_id", "parent_source_id"):
                if record["source"].get(key) is None:
                    record["source"].pop(key, None)
            if part == "checks" and not record.get("subjects"):
                record.pop("subjects", None)
    for key in ("adapter_meta", "subjects", "omitted_sources", "lineage", "conflicts"):
        if not sparse.get(key):
            sparse.pop(key, None)
    return [("nulls", nulled), ("omitted", sparse)]


def test_kernel_and_third_evaluator_agree_on_json_spellings():
    """Null means default and optional fields may be omitted — in both evaluators."""
    import importlib.util

    from ewp.codec import view_from_dict

    pack = Path(__file__).resolve().parents[1] / "docs" / "implementer"
    spec = importlib.util.spec_from_file_location("third_eval", pack / "third_eval.py")
    third = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(third)
    axes = ("acceptance", "conflict", "verification", "currency", "sufficiency")
    checked = 0
    for path in sorted((pack / "fixtures").glob("*.json")):
        raw = json.loads(path.read_text(encoding="utf-8"))
        expected = json.loads((pack / "expected" / path.name).read_text(encoding="utf-8"))
        for label, variant in _json_variants(raw):
            kernel = warrant_now(view_from_dict(variant), POLICY, variant["evaluated_at"]).normative()["warrant"]
            other = third.warrant_now(variant)
            for axis in axes:
                assert kernel[axis] == expected[axis] == other[axis], (path.name, label, axis, kernel[axis], other[axis])
            checked += 1
    print(f"PASS kernel and third evaluator agree on {checked} null/omitted JSON spellings")


if __name__ == "__main__":
    test_kernel_and_third_evaluator_agree_on_json_spellings()
    test_canonical_goldens()
    test_pathological_goldens()
    test_implementer_pack_matches_reference()
    test_invalid_pack_is_refused()
    print("PASS goldens + implementer pack + invalid pack refused")
