#!/usr/bin/env python3
"""MCP façade: warrant is computed, writes need the ingest role, may_act is separate."""

from __future__ import annotations

import io
import json
import subprocess
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from protocol.fixtures import EVAL, fixture_verified_current
from protocol.mcp_server import (
    REFUSE_CLIENT_RISK_POLICY,
    REFUSE_CLIENT_WARRANT,
    REFUSE_EVALUATED_AT_SKEW,
    REFUSE_IMMUTABLE_RECORD,
    REFUSE_INGEST_ROLE,
    REFUSE_INLINE_VIEW,
    REFUSE_INVALID_ACTION,
    REFUSE_INVALID_VIEW,
    REFUSE_MAY_ACT_WITHOUT_ACTION,
    REFUSE_PERSIST_WARRANT,
    REFUSE_UNATTESTED_ORIGIN,
    EwpMcp,
    encode_mcp_message,
    make_http_server,
    read_mcp_message,
)

HIGH_IRREVERSIBLE = {"action_id": "cancel", "kind": "contract.cancel", "reversible": False, "risk": "high"}


def at_eval() -> str:
    return EVAL


def call(server: EwpMcp, method: str, params=None, mid=1):
    msg = {"jsonrpc": "2.0", "id": mid, "method": method}
    if params is not None:
        msg["params"] = params
    return server.handle(msg)


def tool(server: EwpMcp, name: str, arguments: dict):
    reply = call(server, "tools/call", {"name": name, "arguments": arguments})
    return reply["result"]


def error_code(result: dict) -> str | None:
    if not result.get("isError"):
        return None
    return json.loads(result["content"][0]["text"])["error"]


def seeded(**kw) -> EwpMcp:
    server = EwpMcp(ingest_enabled=True, clock=at_eval, **kw)
    tool(server, "ewp_evidence_view_put", {"view": fixture_verified_current().to_dict(), "ingest_attestation": True})
    return server


def test_initialize_and_tools():
    server = EwpMcp()
    init = call(server, "initialize", {"protocolVersion": "2024-11-05"})
    assert init["result"]["serverInfo"]["name"] == "ewp-mcp"
    assert init["result"]["protocolVersion"] == "2024-11-05"
    newer = call(server, "initialize", {"protocolVersion": "2099-01-01"})
    assert newer["result"]["protocolVersion"] == "2025-06-18"
    assert server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
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
    print("PASS initialize (version negotiation) + notifications + tool list")


def test_every_write_requires_ingest_role():
    locked = EwpMcp()
    view = fixture_verified_current().to_dict()
    assert error_code(tool(locked, "ewp_evidence_view_put", {"view": view, "ingest_attestation": True})) == REFUSE_INGEST_ROLE
    # Untrusted origins do not bypass the role.
    untrusted = json.loads(json.dumps(view))
    for part in ("assertions", "evidence", "checks"):
        for row in untrusted[part]:
            row["source"]["origin_type"] = "extract"
    assert error_code(tool(locked, "ewp_evidence_view_put", {"view": untrusted})) == REFUSE_INGEST_ROLE
    # Neither does a metadata-only or conflict-only write.
    patch = {"proposition_id": "P-win", "degraded": False, "freshness_policy_seconds": 10**10,
             "conflicts": [{"conflict_id": "c1", "proposition_ids": ["P-win"], "status": "resolved"}]}
    assert error_code(tool(locked, "ewp_evidence_view_put", {"view": patch})) == REFUSE_INGEST_ROLE
    src = {"source_id": "s", "content_hash": "h", "observed_at": EVAL, "origin_type": "extract"}
    assert error_code(tool(locked, "ewp_check_record", {"proposition_id": "P-win", "check": {
        "check_id": "k9", "method": "inference", "observed_at": EVAL, "result": "supports", "source": src}})) == REFUSE_INGEST_ROLE
    assert error_code(tool(locked, "ewp_evidence_record", {"proposition_id": "P-win", "evidence": {
        "evidence_id": "e9", "content": "x", "observed_at": EVAL, "source": src}})) == REFUSE_INGEST_ROLE
    # With the role, trusted origins still need the explicit declaration.
    server = EwpMcp(ingest_enabled=True)
    assert error_code(tool(server, "ewp_evidence_view_put", {"view": view})) == REFUSE_UNATTESTED_ORIGIN
    ok = tool(server, "ewp_evidence_view_put", {"view": view, "ingest_attestation": True})
    assert ok["structuredContent"]["stored"] is True
    print("PASS every write needs the ingest role; trusted origins also need ingest_attestation")


def test_store_is_append_only_through_mcp():
    server = seeded()
    view = fixture_verified_current().to_dict()
    view["checks"][0]["result"] = "opposes"
    assert error_code(tool(server, "ewp_evidence_view_put", {"view": view, "ingest_attestation": True})) == REFUSE_IMMUTABLE_RECORD
    print("PASS stored check cannot be overwritten by id")


def test_invalid_enum_refused():
    server = EwpMcp(ingest_enabled=True)
    view = fixture_verified_current().to_dict()
    view["checks"][0]["result"] = "pending"
    assert error_code(tool(server, "ewp_evidence_view_put", {"view": view, "ingest_attestation": True})) == REFUSE_INVALID_VIEW
    assert error_code(tool(server, "ewp_warrant_now", {"view": view, "evaluated_at": EVAL})) == REFUSE_INVALID_VIEW
    print("PASS unknown enum values refused at the MCP boundary")


def test_refuse_persist_warrant():
    server = EwpMcp(ingest_enabled=True)
    result = tool(
        server,
        "ewp_evidence_view_put",
        {"warrant": {"proposition_id": "P", "acceptance": "ACCEPTED"}, "ingest_attestation": True},
    )
    assert error_code(result) == REFUSE_PERSIST_WARRANT
    print("PASS WarrantView persist refused")


def test_warrant_roundtrip_and_memory_context():
    server = seeded()
    view = fixture_verified_current()
    w = tool(server, "ewp_warrant_now", {"proposition_id": view.proposition_id, "evaluated_at": EVAL})["structuredContent"]
    axes = w["warrant"]
    assert w["protocol_version"] == "EWP-0.2.0"
    assert w["policy_id"] == "reference-v2"
    assert axes["verification"] == "EXTERNAL"
    assert axes["acceptance"] == "ACCEPTED"
    assert "strength" not in axes and "rationale_codes" not in axes
    ctx = tool(server, "ewp_memory_context", {"proposition_id": view.proposition_id, "query": "os"})["structuredContent"]
    assert ctx["evaluated_at"] == EVAL, "memory_context defaults to server time"
    assert ctx["persona"] is None
    assert ctx["warrant"]["acceptance"] == "ACCEPTED"
    print("PASS warrant_now + memory_context")


def test_inline_view_is_hypothetical():
    view = fixture_verified_current().to_dict()
    anon = EwpMcp()
    w = tool(anon, "ewp_warrant_now", {"view": view, "evaluated_at": EVAL, "ingest_attestation": True})["structuredContent"]
    assert w["warrant"]["verification"] == "INDIRECT", w
    assert w["warrant"]["acceptance"] == "TENTATIVE", w
    assert w["inline_origins_demoted"] == ["tool"]
    ingest = EwpMcp(ingest_enabled=True)
    w = tool(ingest, "ewp_warrant_now", {"view": view, "evaluated_at": EVAL, "ingest_attestation": True})["structuredContent"]
    assert w["warrant"]["verification"] == "EXTERNAL", w
    assert "inline_origins_demoted" not in w
    print("PASS inline view: trusted origins demoted unless ingest role + attestation")


def test_may_act_requires_action_and_stored_view():
    server = seeded()
    pid = fixture_verified_current().proposition_id
    assert error_code(tool(server, "ewp_may_act", {"proposition_id": pid})) == REFUSE_MAY_ACT_WITHOUT_ACTION
    ok = tool(server, "ewp_may_act", {"proposition_id": pid, "action": HIGH_IRREVERSIBLE})["structuredContent"]
    assert ok["decision"] == "MAY_ACT"
    assert ok["evaluated_at"] == EVAL
    anon = EwpMcp(clock=at_eval)
    inline = tool(anon, "ewp_may_act", {"view": fixture_verified_current().to_dict(), "proposition_id": pid, "action": HIGH_IRREVERSIBLE})
    assert error_code(inline) == REFUSE_INLINE_VIEW
    print("PASS may_act gates stored evidence only")


def test_may_act_action_must_be_explicit():
    server = seeded()
    pid = fixture_verified_current().proposition_id
    for bad in (
        {"kind": "x", "reversible": False},
        {"kind": "x", "risk": "critical", "reversible": False},
        {"kind": "x", "risk": "high", "reversible": "false"},
        {"kind": "x", "risk": "high"},
    ):
        assert error_code(tool(server, "ewp_may_act", {"proposition_id": pid, "action": bad})) == REFUSE_INVALID_ACTION, bad
    print("PASS action.risk and action.reversible are required and typed")


def test_may_act_uses_server_clock():
    server = seeded()
    pid = fixture_verified_current().proposition_id
    near = tool(server, "ewp_may_act", {"proposition_id": pid, "action": HIGH_IRREVERSIBLE, "evaluated_at": "2026-09-21T21:02:00+00:00"})
    assert near["structuredContent"]["decision"] == "MAY_ACT"
    far = tool(server, "ewp_may_act", {"proposition_id": pid, "action": HIGH_IRREVERSIBLE, "evaluated_at": "2026-09-22T00:00:00+00:00"})
    assert error_code(far) == REFUSE_EVALUATED_AT_SKEW
    late = EwpMcp(ingest_enabled=True, clock=lambda: "2026-12-01T00:00:00+00:00")
    tool(late, "ewp_evidence_view_put", {"view": fixture_verified_current().to_dict(), "ingest_attestation": True})
    stale = tool(late, "ewp_may_act", {"proposition_id": pid, "action": HIGH_IRREVERSIBLE})["structuredContent"]
    assert stale["decision"] == "DENY", stale
    print("PASS may_act evaluates at server time; distant evaluated_at refused")


def test_risk_policy_is_operator_only():
    pid = fixture_verified_current().proposition_id
    anon = EwpMcp(clock=at_eval)
    refused = tool(anon, "ewp_may_act", {"proposition_id": pid, "action": HIGH_IRREVERSIBLE, "risk_policy": {"high_requires_accepted": False}})
    assert error_code(refused) == REFUSE_CLIENT_RISK_POLICY
    server = seeded()
    open_conflict = fixture_verified_current().to_dict()
    open_conflict["proposition_id"] = "P-open"
    open_conflict["conflicts"] = [{"conflict_id": "c-open", "proposition_ids": ["P-open"], "status": "open"}]
    for part in ("assertions", "evidence"):
        for row in open_conflict[part]:
            row["proposition_id"] = "P-open"
    tool(server, "ewp_evidence_view_put", {"view": open_conflict, "ingest_attestation": True})
    reversible_high = {"kind": "x", "risk": "high", "reversible": True}
    strict = tool(server, "ewp_may_act", {"proposition_id": "P-open", "action": reversible_high})["structuredContent"]
    lenient = tool(server, "ewp_may_act", {"proposition_id": "P-open", "action": reversible_high, "risk_policy": {
        "high_requires_accepted": False, "high_requires_no_open_conflict": False}})["structuredContent"]
    assert strict["decision"] == "DENY", strict
    assert lenient["decision"] == "MAY_ACT", lenient
    print("PASS risk_policy flags honored for the operator, refused for anonymous callers")


def test_may_act_refuses_client_warrant():
    server = seeded()
    pid = fixture_verified_current().proposition_id
    forged = {"acceptance": "ACCEPTED", "conflict": "NONE", "verification": "EXTERNAL", "currency": "CURRENT", "sufficiency": "SUFFICIENT"}
    result = tool(server, "ewp_may_act", {"proposition_id": pid, "action": HIGH_IRREVERSIBLE, "warrant": forged})
    assert error_code(result) == REFUSE_CLIENT_WARRANT
    print("PASS client-supplied WarrantView refused")


def test_stdio_framing_is_newline_delimited():
    payload = {"jsonrpc": "2.0", "id": 1, "method": "ping", "params": {"note": "line\nbreak"}}
    framed = encode_mcp_message(payload)
    assert framed.endswith(b"\n") and framed.count(b"\n") == 1, framed
    assert not framed.startswith(b"Content-Length")
    stream = io.BytesIO(b"\n" + framed + framed)
    assert read_mcp_message(stream) == payload
    assert read_mcp_message(stream) == payload
    assert read_mcp_message(stream) is None
    print("PASS stdio framing: one JSON message per line")


def test_stdio_subprocess_session():
    """Drive the real process the way an MCP client does."""
    proc = subprocess.Popen(
        [sys.executable, "-m", "protocol.mcp_server", "--allow-ingest"],
        cwd=ROOT,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        def send(msg):
            proc.stdin.write(encode_mcp_message(msg))
            proc.stdin.flush()

        def recv():
            return json.loads(proc.stdout.readline())

        send({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}}})
        assert recv()["result"]["protocolVersion"] == "2025-06-18"
        send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        send({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        assert len(recv()["result"]["tools"]) == 7
        send({"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "ewp_evidence_view_put", "arguments": {
            "view": fixture_verified_current().to_dict(), "ingest_attestation": True}}})
        assert recv()["result"]["structuredContent"]["stored"] is True
        send({"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "ewp_warrant_now", "arguments": {
            "proposition_id": "P-win", "evaluated_at": EVAL}}})
        assert recv()["result"]["structuredContent"]["warrant"]["acceptance"] == "ACCEPTED"
    finally:
        proc.stdin.close()
        proc.wait(timeout=10)
        proc.stdout.close()
        proc.stderr.close()
    print("PASS stdio subprocess session (initialize, notification, tools/list, tools/call)")


def test_stdio_with_official_sdk():
    """Interop with the official MCP Python SDK when it is installed."""
    try:
        import anyio  # noqa: F401
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
    except ImportError:
        print("SKIP official MCP SDK not installed (pip install mcp)")
        return

    negotiated: list[str] = []

    async def run() -> None:
        params = StdioServerParameters(command=sys.executable, args=["-m", "protocol.mcp_server"], cwd=str(ROOT))
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                init = await session.initialize()
                negotiated.append(str(getattr(init, "protocol_version", None) or getattr(init, "protocolVersion", "?")))
                tools = await session.list_tools()
                assert len(tools.tools) == 7
                result = await session.call_tool("ewp_warrant_now", {"view": fixture_verified_current().to_dict(), "evaluated_at": EVAL})
                # SDK 1.x exposes structuredContent; 2.x exposes structured_content.
                body = getattr(result, "structured_content", None) or getattr(result, "structuredContent", None)
                if body is None:
                    body = json.loads(result.content[0].text)
                assert body["warrant"]["verification"] == "INDIRECT", body

    import anyio

    anyio.run(run)
    print(f"PASS official MCP SDK client over stdio (negotiated {negotiated[0]})")


def test_http_roles_and_limits():
    try:
        make_http_server(EwpMcp(ingest_enabled=True), "127.0.0.1", 0)
    except ValueError:
        pass
    else:
        raise AssertionError("--allow-ingest must not be combined with HTTP")
    server = EwpMcp(ingest_token="s3cret", clock=at_eval)
    httpd = make_http_server(server, "127.0.0.1", 0)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        def post(body: bytes, token: str | None = None):
            req = urllib.request.Request(f"http://127.0.0.1:{port}/mcp", data=body, method="POST")
            req.add_header("Content-Type", "application/json")
            if token:
                req.add_header("Authorization", f"Bearer {token}")
            try:
                with urllib.request.urlopen(req, timeout=5) as resp:
                    return resp.status, json.loads(resp.read() or b"null")
            except urllib.error.HTTPError as exc:
                return exc.code, None

        put = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "ewp_evidence_view_put", "arguments": {
            "view": fixture_verified_current().to_dict(), "ingest_attestation": True}}}).encode()
        status, body = post(put)
        assert status == 200 and error_code(body["result"]) == REFUSE_INGEST_ROLE
        status, body = post(put, token="wrong")
        assert error_code(body["result"]) == REFUSE_INGEST_ROLE
        status, body = post(put, token="s3cret")
        assert body["result"]["structuredContent"]["stored"] is True
        # Declare an oversized body without sending it: the server must refuse from headers alone.
        import socket

        with socket.create_connection(("127.0.0.1", port), timeout=5) as sock:
            sock.sendall(b"POST /mcp HTTP/1.1\r\nHost: x\r\nContent-Length: 2000000\r\n\r\n")
            status_line = sock.makefile("rb").readline()
        assert b" 413 " in status_line, status_line
        status, _ = post(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}).encode())
        assert status == 202, status
    finally:
        httpd.shutdown()
        httpd.server_close()
    print("PASS HTTP: evaluate-only without token, writes with token, body limit, stdio-only --allow-ingest")


def main() -> int:
    test_initialize_and_tools()
    test_every_write_requires_ingest_role()
    test_store_is_append_only_through_mcp()
    test_invalid_enum_refused()
    test_refuse_persist_warrant()
    test_warrant_roundtrip_and_memory_context()
    test_inline_view_is_hypothetical()
    test_may_act_requires_action_and_stored_view()
    test_may_act_action_must_be_explicit()
    test_may_act_uses_server_clock()
    test_risk_policy_is_operator_only()
    test_may_act_refuses_client_warrant()
    test_stdio_framing_is_newline_delimited()
    test_stdio_subprocess_session()
    test_stdio_with_official_sdk()
    test_http_roles_and_limits()
    print("MCP SUITE PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
