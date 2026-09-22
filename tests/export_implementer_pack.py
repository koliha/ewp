#!/usr/bin/env python3
"""Write docs/implementer/{fixtures,expected} from the current evaluators.

Expected files contain only the five axes. Regenerating them is allowed when
reference-v1 is revised; it is not a protocol bump.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from protocol.fixtures import EVAL
from protocol.laundering import PACK as LAUNDER, EVAL_AT
from protocol.pathological import PACK as PATHO
from protocol.types import Policy
from protocol.warrant import warrant_now
from tests.runner import FIXTURES

ROOT = Path(__file__).resolve().parents[1] / "docs" / "implementer"
AXES = ("acceptance", "conflict", "verification", "currency", "sufficiency")
POLICY = Policy()


def dump(name: str, view, evaluated_at: str) -> None:
    payload = view.to_dict()
    payload["evaluated_at"] = evaluated_at
    (ROOT / "fixtures" / f"{name}.json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    w = warrant_now(view, POLICY, evaluated_at).warrant
    expected = {k: getattr(w, k) for k in AXES}
    expected["policy_version"] = POLICY.version
    expected["evaluated_at"] = evaluated_at
    (ROOT / "expected" / f"{name}.json").write_text(json.dumps(expected, indent=2, sort_keys=True) + "\n")
    print(name)


def main() -> None:
    (ROOT / "fixtures").mkdir(parents=True, exist_ok=True)
    (ROOT / "expected").mkdir(parents=True, exist_ok=True)
    for name, cases in FIXTURES:
        _pid, view, evaluated_at = cases[0]
        dump(name, view, evaluated_at)
    for name, factory in PATHO:
        dump(name, factory(), EVAL)
    for name, factory in LAUNDER:
        dump(name, factory(), EVAL_AT.get(name, EVAL))


if __name__ == "__main__":
    main()
