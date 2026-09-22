#!/usr/bin/env python3
"""MCP façade: warrant is computed, origins are attested, may_act is separate."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from protocol.fixtures import EVAL, fixture_verified_current
from protocol.mcp_server import (
    REFUSE_MAY_ACT_WITHOUT_ACTION,
    REFUSE_PERSIST_WARRANT,
    REFUSE_UNATTESTED_ORIGIN,
    EwpMcp,
)


def call(server: EwpMcp, method: str, params=None, mid=1):
    msg = {"jsonrpc": "2.0", "id": mid, "method": method}
    if params is not None:
        msg["params"] = params
    return server.handle(msg)


def tool(server: EwpMcp, name: str, arguments: dict):
    reply = call(server, "tools/call", {"name": name, "arguments": arguments})
    return reply["result"]


def test_initialize_and_tools():
    server = EwpMcp()
    init = call(server, "initialize", {})
    assert init["result"]["serverInfo"]["name"] == "ewp-mcp"
    tools = call(server, "tools/list")["result"]["tools"]
    names = {t["name"] for t in tools}
    assert names == {
        "ewp_warrant_now",
        "ewp_evidence_view_put",
        "ewp_evidence_view_get",
        "ewp_check_record",
        "ewp_evidence_record",
        "ewp_may_act",
        "ewp_memory_context",
    }
    print("PASS initialize + tool list")


def test_put_requires_attestation_for_trusted_origin():
    server = EwpMcp()
    view = fixture_verified_current().to_dict()
    result = tool(server, "ewp_evidence_view_put", {"view": view})
    assert result["isError"] is True
    body = json.loads(result["content"][0]["text"])
    assert body["error"] == REFUSE_UNATTESTED_ORIGIN
    ok = tool(server, "ewp_evidence_view_put", {"view": view, "ingest_attestation": True})
    assert ok["structuredContent"]["stored"] is True
    print("PASS unattested trusted origin refused")


def test_refuse_persist_warrant():
    server = EwpMcp()
    result = tool(
        server,
        "ewp_evidence_view_put",
        {"warrant": {"proposition_id": "P", "acceptance": "ACCEPTED"}, "ingest_attestation": True},
    )
    assert result["isError"] is True
    body = json.loads(result["content"][0]["text"])
    assert body["error"] == REFUSE_PERSIST_WARRANT
    print("PASS WarrantView persist refused")


def test_warrant_roundtrip_and_memory_context():
    server = EwpMcp()
    view = fixture_verified_current()
    tool(server, "ewp_evidence_view_put", {"view": view.to_dict(), "ingest_attestation": True})
    w = tool(server, "ewp_warrant_now", {"proposition_id": view.proposition_id, "evaluated_at": EVAL})
    axes = w["structuredContent"]["warrant"]
    assert axes["verification"] == "EXTERNAL"
    assert axes["acceptance"] == "ACCEPTED"
    assert "strength" not in axes
    ctx = tool(
        server,
        "ewp_memory_context",
        {"proposition_id": view.proposition_id, "evaluated_at": EVAL, "query": "os"},
    )["structuredContent"]
    assert ctx["persona"] is None
    assert ctx["warrant"]["acceptance"] == "ACCEPTED"
    print("PASS warrant_now + memory_context")


def test_may_act_requires_action():
    server = EwpMcp()
    view = fixture_verified_current()
    tool(server, "ewp_evidence_view_put", {"view": view.to_dict(), "ingest_attestation": True})
    denied = tool(server, "ewp_may_act", {"proposition_id": view.proposition_id, "evaluated_at": EVAL})
    assert denied["isError"] is True
    body = json.loads(denied["content"][0]["text"])
    assert body["error"] == REFUSE_MAY_ACT_WITHOUT_ACTION
    ok = tool(
        server,
        "ewp_may_act",
        {
            "proposition_id": view.proposition_id,
            "evaluated_at": EVAL,
            "action": {"action_id": "cancel", "kind": "contract.cancel", "reversible": False, "risk": "high"},
        },
    )["structuredContent"]
    assert ok["decision"] == "MAY_ACT"
    print("PASS may_act separate gate")


def test_inline_view_does_not_need_store():
    server = EwpMcp()
    view = fixture_verified_current().to_dict()
    w = tool(server, "ewp_warrant_now", {"view": view, "evaluated_at": EVAL})["structuredContent"]
    assert w["warrant"]["verification"] == "EXTERNAL"
    print("PASS inline view warrant_now")


def main() -> int:
    test_initialize_and_tools()
    test_put_requires_attestation_for_trusted_origin()
    test_refuse_persist_warrant()
    test_warrant_roundtrip_and_memory_context()
    test_may_act_requires_action()
    test_inline_view_does_not_need_store()
    print("MCP SUITE PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
