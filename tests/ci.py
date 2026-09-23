#!/usr/bin/env python3
"""CI gate for EWP.

1. lock hashes (fixtures, evaluator, policy, goldens, implementer pack) match
2. goldens and the implementer pack match the reference evaluator
3. canonical, pathological, and hardening packs pass
4. every fixture survives every adapter with the same axes
5. fake Graphiti remains epistemically isolated
6. live Graphiti/Mem0 mappings keep origin/lineage/degraded rules
7. MCP façade: ingest role on every write, inline views hypothetical, stdio framing
8. an independent third evaluator agrees from the written policy alone
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ewp.release import LOCK_KEYS, ci_surface_hash, current_hashes, metadata, write_lock, write_text_atomic
from ewp.versions import POLICY, PROTOCOL

STAMP = ROOT / "tests" / ".last_ci.json"


def run(cmd: list[str]) -> int:
    print("+", " ".join(cmd))
    return subprocess.call(cmd, cwd=ROOT)


def check_lock() -> None:
    lock = ROOT / "RELEASE.lock.json"
    if not lock.exists():
        raise SystemExit("RELEASE.lock.json missing: run python3 tests/ci.py --write-lock")
    pinned = json.loads(lock.read_text(encoding="utf-8"))
    if (pinned.get("protocol"), pinned.get("policy")) != (PROTOCOL, POLICY):
        raise SystemExit(
            f"lock identity {pinned.get('protocol')}/{pinned.get('policy')} "
            f"!= code identity {PROTOCOL}/{POLICY}"
        )
    current = current_hashes()
    for key in LOCK_KEYS:
        if pinned.get(key) != current[key]:
            raise SystemExit(
                f"SILENT DRIFT on {key}\n"
                f"  lock:    {pinned.get(key)}\n"
                f"  current: {current[key]}\n"
                "Bump the protocol or policy version explicitly. Do not refresh goldens to please a store."
            )
    print("lock hashes match")
    print(json.dumps({k: pinned[k] for k in ("protocol", "policy", *LOCK_KEYS)}, indent=2))


def write_stamp(ok: bool, surface: str, **extra) -> None:
    """`surface` is hashed before the run starts: the stamp names the tree that was tested."""
    body = {"ok": ok, "protocol": PROTOCOL, "policy": POLICY, **current_hashes(), "ci_surface_sha256": surface, **extra}
    write_text_atomic(STAMP, json.dumps(body, indent=2) + "\n")


def main() -> int:
    surface = ci_surface_hash()
    check_lock()
    steps = [
        [sys.executable, "tests/test_goldens.py"],
        [sys.executable, "tests/test_conformance.py"],
        [sys.executable, "tests/runner.py"],
        [sys.executable, "tests/runner_graphiti.py"],
        [sys.executable, "tests/runner_pathological.py"],
        [sys.executable, "tests/test_graphiti_adapter.py"],
        [sys.executable, "tests/test_pathological.py"],
        [sys.executable, "tests/test_laundering.py"],
        [sys.executable, "tests/test_adapter_roundtrip.py"],
        [sys.executable, "tests/test_live_adapters.py"],
        [sys.executable, "tests/test_mcp.py"],
        [sys.executable, "tests/test_hardening.py"],
        [sys.executable, "tests/test_ingest_cli.py"],
        [sys.executable, "docs/implementer/third_eval.py"],
    ]
    for cmd in steps:
        rc = run(cmd)
        if rc != 0:
            print("CI FAIL", cmd)
            write_stamp(False, surface, failed=cmd[1:])
            return rc
    print(
        "CI PASS: lock, goldens, implementer pack, hardening pack, adapter round trips, "
        "fake Graphiti isolation, live mappings, MCP façade, third evaluator"
    )
    print(json.dumps(metadata(), indent=2))
    if ci_surface_hash() != surface:
        print("CI FAIL: files changed while CI was running; rerun")
        write_stamp(False, surface, failed=["tree changed during run"])
        return 1
    write_stamp(True, surface)
    return 0


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--write-lock":
        print(write_lock())
        raise SystemExit(0)
    raise SystemExit(main())
