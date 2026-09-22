"""Goldens are the protocol. Stores do not get to rewrite them."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from protocol.fixtures import EVAL
from protocol.pathological import PACK
from protocol.types import Policy
from protocol.warrant import warrant_now
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


if __name__ == "__main__":
    test_canonical_goldens()
    test_pathological_goldens()
    print("PASS goldens")
