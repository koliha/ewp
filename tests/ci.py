#!/usr/bin/env python3
"""CI gate for EWP.

1. goldens never drift silently
2. all 26 fixtures pass reference-v1
3. SQLite and JSON remain equivalent
4. fake Graphiti remains epistemically isolated
5. live Graphiti/Mem0 mappings keep origin/lineage/degraded rules
6. MCP façade refuses unattested trusted origins and WarrantView persistence
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from protocol.release import (
    evaluator_set_hash,
    fixture_set_hash,
    golden_set_hash,
    metadata,
    write_lock,
)


def run(cmd: list[str]) -> int:
    print("+", " ".join(cmd))
    return subprocess.call(cmd, cwd=ROOT)


def check_lock() -> None:
    lock = ROOT / "RELEASE.lock.json"
    current = {
        "fixture_set_sha256": fixture_set_hash(),
        "evaluator_set_sha256": evaluator_set_hash(),
        "golden_set_sha256": golden_set_hash(),
    }
    if not lock.exists():
        raise SystemExit("RELEASE.lock.json missing — run python3 -m protocol.release")
    pinned = json.loads(lock.read_text())
    for key, value in current.items():
        if pinned.get(key) != value:
            raise SystemExit(
                f"SILENT DRIFT on {key}\n"
                f"  lock:    {pinned.get(key)}\n"
                f"  current: {value}\n"
                "Bump protocol/policy version explicitly. Do not refresh goldens to please a store."
            )
    print("lock hashes match")
    print(json.dumps({k: pinned[k] for k in ("protocol", "policy", "fixture_set_sha256", "evaluator_set_sha256", "golden_set_sha256")}, indent=2))


def main() -> int:
    check_lock()
    steps = [
        [sys.executable, "tests/test_goldens.py"],
        [sys.executable, "tests/test_conformance.py"],
        [sys.executable, "tests/runner.py"],
        [sys.executable, "tests/test_graphiti_adapter.py"],
        [sys.executable, "tests/test_pathological.py"],
        [sys.executable, "tests/test_laundering.py"],
        [sys.executable, "tests/test_live_adapters.py"],
        [sys.executable, "tests/test_mcp.py"],
        [sys.executable, "docs/implementer/third_eval.py"],
    ]
    for cmd in steps:
        rc = run(cmd)
        if rc != 0:
            print("CI FAIL", cmd)
            (ROOT / "tests" / ".last_ci.json").write_text(json.dumps({"ok": False, "failed": cmd}, indent=2) + "\n")
            return rc
    print("CI PASS — goldens, 26 fixtures, SQLite=JSON, fake Graphiti isolated, laundering pack, live mappings, MCP façade, third evaluator")
    print(json.dumps(metadata(), indent=2))
    (ROOT / "tests" / ".last_ci.json").write_text(json.dumps({"ok": True, "protocol": metadata()["protocol"], "policy": metadata()["policy"]}, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--write-lock":
        print(write_lock())
        raise SystemExit(0)
    raise SystemExit(main())
