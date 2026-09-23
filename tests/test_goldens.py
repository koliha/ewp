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
    from ewp.classify import InvalidEvidenceView
    from ewp.codec import view_from_dict
    from ewp.laundering import INVALID_PACK

    pack = Path(__file__).resolve().parents[1] / "docs" / "implementer" / "invalid"
    files = sorted(pack.glob("*.json"))
    assert len(files) == len(INVALID_PACK), (len(files), len(INVALID_PACK))
    for path in files:
        raw = json.loads(path.read_text(encoding="utf-8"))
        try:
            view_from_dict(raw)
        except InvalidEvidenceView:
            continue
        raise AssertionError(f"{path.name} was accepted")


if __name__ == "__main__":
    test_canonical_goldens()
    test_pathological_goldens()
    test_implementer_pack_matches_reference()
    test_invalid_pack_is_refused()
    print("PASS goldens + implementer pack + invalid pack refused")
