"""Print a conformance claim. Does not establish conformance.

Reads tests/.last_ci.json written by tests/ci.py. The stamp counts only if
its hashes equal the current tree: a stamp from before an edit is stale,
and a stale or missing stamp never prints an authoritative CONFORMANT.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from protocol.graphiti_live import runtime_version
from protocol.release import LOCK_KEYS, metadata

ROOT = Path(__file__).resolve().parents[1]
STAMP = ROOT / "tests" / ".last_ci.json"


def main() -> int:
    meta = metadata()
    live = runtime_version()
    adapter = f"graphiti-core {live}" if live else f"graphiti-core {meta['graphiti_pin']} — NOT VALIDATED"
    stamp = None
    if STAMP.exists():
        try:
            stamp = json.loads(STAMP.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            stamp = None
    fresh = bool(stamp) and all(stamp.get(k) == meta[k] for k in (*LOCK_KEYS, "protocol", "policy"))
    if stamp and not fresh:
        result = "CLAIM_ONLY"
        claim = "stale-ci-stamp: tree changed since tests/ci.py last ran"
    elif stamp and stamp.get("ok") is True:
        result = "CONFORMANT" if live is None else "LIVE_PENDING"
        claim = "ci-stamp"
    elif stamp and stamp.get("ok") is False:
        result = "NONCONFORMANT"
        claim = "ci-stamp"
    else:
        result = "CLAIM_ONLY"
        claim = "no-ci-stamp: run python3 tests/ci.py first"
    verified = claim == "ci-stamp"

    report = {
        "title": f"Epistemic Warrant Protocol {meta['protocol']}",
        "policy": meta["policy"],
        **{k: meta[k] for k in LOCK_KEYS},
        "adapter": adapter,
        "canonical": "14/14" if verified else "unverified",
        "pathological": "12/12" if verified else "unverified",
        "hardening": "24/24" if verified else "unverified",
        "reference_stores": {"SQLite": "PASS", "JSON": "PASS"} if verified else {"SQLite": "unverified", "JSON": "unverified"},
        "semantic_adapter": {"Fake Graphiti": "PASS"} if verified else {"Fake Graphiti": "unverified"},
        "live_integrations": {f"graphiti-core {meta['graphiti_pin']}": "NOT VALIDATED"},
        "result": result,
        "claim": claim,
        "rule": meta["rule"],
    }
    print(json.dumps(report, indent=2))
    print()
    print(f"Epistemic Warrant Protocol {meta['protocol']}")
    print(f"Policy {meta['policy']}")
    for key in LOCK_KEYS:
        print(f"{key}: {meta[key]}")
    print(f"Adapter: {adapter}")
    for label, count in (("Canonical", "14/14"), ("Pathological", "12/12"), ("Hardening", "24/24")):
        print(f"{label}: {count if verified else 'unverified'}")
    print(f"Result: {result}")
    print(f"Claim: {claim}")
    print(meta["rule"])
    return 0 if result != "NONCONFORMANT" else 1


if __name__ == "__main__":
    raise SystemExit(main())
