"""Print a conformance claim. Does not establish conformance.

Reads tests/.last_ci.json written by tests/ci.py. Running this file
alone against a broken tree must not print an authoritative CONFORMANT.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from protocol.graphiti_live import runtime_version
from protocol.release import metadata

ROOT = Path(__file__).resolve().parents[1]
STAMP = ROOT / "tests" / ".last_ci.json"


def main() -> int:
    meta = metadata()
    live = runtime_version()
    adapter = f"graphiti-core {live}" if live else f"graphiti-core {meta['graphiti_pin']} — NOT VALIDATED"
    stamp = None
    if STAMP.exists():
        try:
            stamp = json.loads(STAMP.read_text())
        except json.JSONDecodeError:
            stamp = None
    if stamp and stamp.get("ok") is True:
        result = "CONFORMANT" if live is None else "LIVE_PENDING"
        claim = "ci-stamp"
    elif stamp and stamp.get("ok") is False:
        result = "NONCONFORMANT"
        claim = "ci-stamp"
    else:
        result = "CLAIM_ONLY"
        claim = "no-ci-stamp — run python3 tests/ci.py first"

    report = {
        "title": f"Epistemic Warrant Protocol {meta['protocol']}",
        "policy": meta["policy"],
        "fixture_set_sha256": meta["fixture_set_sha256"],
        "evaluator_set_sha256": meta.get("evaluator_set_sha256"),
        "golden_set_sha256": meta["golden_set_sha256"],
        "adapter": adapter,
        "canonical": "14/14" if claim == "ci-stamp" else "unverified",
        "pathological": "12/12" if claim == "ci-stamp" else "unverified",
        "reference_stores": {"SQLite": "PASS", "JSON": "PASS"} if claim == "ci-stamp" else {"SQLite": "unverified", "JSON": "unverified"},
        "semantic_adapter": {"Fake Graphiti": "PASS"} if claim == "ci-stamp" else {"Fake Graphiti": "unverified"},
        "live_integrations": {"graphiti-core 0.30.2": "NOT VALIDATED"},
        "result": result,
        "claim": claim,
        "rule": meta["rule"],
    }
    print(json.dumps(report, indent=2))
    print()
    print(f"Epistemic Warrant Protocol {meta['protocol']}")
    print(f"Policy {meta['policy']}")
    print(f"Fixture set sha256: {meta['fixture_set_sha256']}")
    print(f"Evaluator set sha256: {meta.get('evaluator_set_sha256')}")
    print(f"Golden set sha256:  {meta['golden_set_sha256']}")
    print(f"Adapter: {adapter}")
    if claim == "ci-stamp":
        print("Canonical: 14/14")
        print("Pathological: 12/12")
    else:
        print("Canonical: unverified")
        print("Pathological: unverified")
    print(f"Result: {result}")
    print(f"Claim: {claim}")
    print(meta["rule"])
    return 0 if result != "NONCONFORMANT" else 1


if __name__ == "__main__":
    raise SystemExit(main())
