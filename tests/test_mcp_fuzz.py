#!/usr/bin/env python3
"""Fuzz every MCP tool argument (top level and nested objects) with awkward
values. Each call must succeed or be refused with an EWP_* code: never a
JSON-RPC server error, never an exception escaping the server."""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ewp.fixtures import EVAL, fixture_verified_current  # noqa: E402
from ewp.mcp_server import EwpMcp  # noqa: E402

VALUES = [None, "", 0, -1, False, True, [], {}, "x", 1.5, 10**400, ["a"], {"a": 1}]
SRC = {"source_id": "s-f", "content_hash": "h", "observed_at": EVAL, "origin_type": "tool"}
BASE = {
    "ewp_warrant_now": {"proposition_id": "P-win", "evaluated_at": EVAL},
    "ewp_evidence_view_put": {"view": fixture_verified_current().to_dict(), "ingest_attestation": True},
    "ewp_evidence_view_get": {"proposition_id": "P-win"},
    "ewp_check_record": {"proposition_id": "P-win", "ingest_attestation": True, "check": {
        "check_id": "k-f", "method": "tool_observation", "observed_at": EVAL, "result": "supports", "source": SRC}},
    "ewp_evidence_record": {"proposition_id": "P-win", "ingest_attestation": True, "text": "t",
                            "assertion_confidence": 0.7, "evidence": {
                                "evidence_id": "e-f", "content": "c", "observed_at": EVAL,
                                "polarity": "supports", "source": SRC}},
    "ewp_may_act": {"proposition_id": "P-win", "action": {"risk": "low", "reversible": True},
                    "risk_policy": {"high_requires_accepted": True}},
    "ewp_memory_context": {"proposition_id": "P-win", "evaluated_at": EVAL},
    "ewp_list_propositions": {"query": "P", "limit": 10},
}


def _server() -> EwpMcp:
    s = EwpMcp(ingest_enabled=True, clock=lambda: EVAL)
    s.handle({"jsonrpc": "2.0", "id": 0, "method": "tools/call", "params": {
        "name": "ewp_evidence_view_put",
        "arguments": {"view": fixture_verified_current().to_dict(), "ingest_attestation": True}}})
    return s


def _call(s: EwpMcp, name: str, args) -> str:
    try:
        reply = s.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": args}})
    except Exception as exc:
        return f"ESCAPED {type(exc).__name__}: {exc}"[:160]
    if "error" in reply:
        return f"JSONRPC {reply['error'].get('code')}: {reply['error'].get('message')}"[:160]
    r = reply["result"]
    if r.get("isError"):
        code = str(json.loads(r["content"][0]["text"]).get("error", ""))
        return "REFUSED" if code.startswith("EWP_") else f"ODD {code}"
    return "OK"


def _targets(args: dict, prefix=()):
    for k, v in args.items():
        yield prefix + (k,)
        if isinstance(v, dict) and k != "view":
            yield from _targets(v, prefix + (k,))


def main() -> int:
    bad = []
    runs = 0
    for name, base in BASE.items():
        for value in (None, "x", [], 5):  # the whole arguments object
            result = _call(_server(), name, value)
            runs += 1
            if result not in ("OK", "REFUSED"):
                bad.append((name, "<arguments>", repr(value), result))
        for path in list(_targets(base)):
            for value in VALUES:
                args = copy.deepcopy(base)
                node = args
                for p in path[:-1]:
                    node = node[p]
                node[path[-1]] = copy.deepcopy(value)
                result = _call(_server(), name, args)
                runs += 1
                if result not in ("OK", "REFUSED"):
                    bad.append((name, ".".join(map(str, path)), repr(value)[:30], result))
    if bad:
        for row in bad[:20]:
            print("FAIL", *row)
        return 1
    print(f"PASS {runs} fuzzed MCP tool calls: each succeeded or was refused with an EWP code")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
