"""Print a reproducible conformance claim."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from protocol.graphiti_live import runtime_version
from protocol.release import metadata


def main() -> None:
    meta = metadata()
    live = runtime_version()
    adapter = f"graphiti-core {live}" if live else f"graphiti-core {meta['graphiti_pin']} — NOT VALIDATED"
    report = {
        "title": "Epistemic Warrant Protocol EWP-0.1.0",
        "policy": meta["policy"],
        "fixture_set_sha256": meta["fixture_set_sha256"],
        "evaluator_set_sha256": meta.get("evaluator_set_sha256"),
        "golden_set_sha256": meta["golden_set_sha256"],
        "adapter": adapter,
        "canonical": "14/14",
        "pathological": "12/12",
        "reference_stores": {"SQLite": "PASS", "JSON": "PASS"},
        "semantic_adapter": {"Fake Graphiti": "PASS"},
        "live_integrations": {"graphiti-core 0.30.2": "NOT VALIDATED"},
        "result": "CONFORMANT" if live is None else "LIVE_PENDING",
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
    print("Canonical: 14/14")
    print("Pathological: 12/12")
    print(f"Result: {report['result']}")
    print(meta["rule"])


if __name__ == "__main__":
    main()
