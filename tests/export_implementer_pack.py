#!/usr/bin/env python3
"""Write docs/implementer/{fixtures,expected} from the current evaluators.

Expected files contain the five axes plus protocol and policy identity.
They are hashed into RELEASE.lock.json. Regenerating them requires a
policy or protocol version change, then `python3 tests/ci.py --write-lock`.
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
from protocol.versions import PROTOCOL
from protocol.warrant import warrant_now
from tests.runner import FIXTURES

ROOT = Path(__file__).resolve().parents[1] / "docs" / "implementer"
AXES = ("acceptance", "conflict", "verification", "currency", "sufficiency")
POLICY = Policy()


def _write(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


def dump(name: str, view, evaluated_at: str) -> None:
    payload = view.to_dict()
    payload["evaluated_at"] = evaluated_at
    _write(ROOT / "fixtures" / f"{name}.json", payload)
    w = warrant_now(view, POLICY, evaluated_at).warrant
    expected = {k: getattr(w, k) for k in AXES}
    expected["protocol_version"] = PROTOCOL
    expected["policy_version"] = POLICY.version
    expected["evaluated_at"] = evaluated_at
    _write(ROOT / "expected" / f"{name}.json", expected)
    print(name)


def main() -> None:
    for sub in ("fixtures", "expected"):
        (ROOT / sub).mkdir(parents=True, exist_ok=True)
        for old in (ROOT / sub).glob("*.json"):
            old.unlink()
    for name, cases in FIXTURES:
        _pid, view, evaluated_at = cases[0]
        dump(name, view, evaluated_at)
    for name, factory in PATHO:
        dump(name, factory(), EVAL)
    for name, factory in LAUNDER:
        dump(name, factory(), EVAL_AT.get(name, EVAL))


if __name__ == "__main__":
    main()
