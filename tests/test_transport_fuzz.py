#!/usr/bin/env python3
"""JSON-RPC and HTTP transport fuzz. handle() must answer every
malformed request with a specific JSON-RPC error (never the generic -32000),
and the HTTP server must stay up and answer each bad request properly."""
import http.client
import json
import sys
import threading
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ewp.fixtures import EVAL, fixture_verified_current  # noqa: E402
from ewp.mcp_server import EwpMcp, make_http_server  # noqa: E402

WEIRD = [None, "", 0, -1, True, False, 1.5, [], {}, [1], {"a": 1}, "x", 10**400]
METHODS = ["initialize", "ping", "tools/list", "tools/call", "resources/list", "resources/read",
           "resources/templates/list", "prompts/list", "nope"]


def server():
    s = EwpMcp(ingest_enabled=True, clock=lambda: EVAL)
    s.handle({"jsonrpc": "2.0", "id": 0, "method": "tools/call", "params": {
        "name": "ewp_evidence_view_put", "arguments": {"view": fixture_verified_current().to_dict(), "ingest_attestation": True}}})
    return s


def classify(reply):
    if reply is None:
        return "notification"
    if "error" in reply:
        return f"error {reply['error'].get('code')}"
    return "ok"


def main():
    bad = Counter()
    ex = {}
    runs = 0
    s = server()
    # 1. params shapes for every method; uri / name shapes
    for method in METHODS:
        for params in WEIRD:
            reply = s.handle({"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
            runs += 1
            c = classify(reply)
            if c == "error -32000":
                bad[("params", method, type(params).__name__)] += 1
                ex.setdefault(("params", method, type(params).__name__), reply["error"]["message"][:80])
        for key in ("uri", "name", "protocolVersion"):
            for value in WEIRD:
                reply = s.handle({"jsonrpc": "2.0", "id": 1, "method": method, "params": {key: value}})
                runs += 1
                if classify(reply) == "error -32000":
                    bad[(key, method, repr(value)[:12])] += 1
                    ex.setdefault((key, method, repr(value)[:12]), reply["error"]["message"][:80])
    # 2. message shapes and ids
    for message in [None, [], [1], "x", 5, {}, {"id": 1}, {"method": 5, "id": 1}, {"method": [], "id": 1},
                    {"method": {}, "id": 1}]:
        runs += 1
        try:
            reply = s.handle(message)
            if classify(reply) == "error -32000":
                bad[("message", repr(message)[:20])] += 1
        except Exception as exc:
            bad[("message ESCAPED", repr(message)[:20], type(exc).__name__)] += 1
    for mid in WEIRD:
        runs += 1
        reply = s.handle({"jsonrpc": "2.0", "id": mid, "method": "ping"})
        if reply is not None and "result" in reply and (isinstance(mid, bool) or not isinstance(mid, (str, int))):
            bad[("id accepted", repr(mid)[:12])] += 1
    # 3. HTTP
    srv = EwpMcp(clock=lambda: EVAL)
    httpd = make_http_server(srv, "127.0.0.1", 0)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    requests = [
        ("POST", "/mcp", b"not json", {"Content-Type": "application/json"}),
        ("POST", "/mcp", b"[1,2]", {}),
        ("POST", "/mcp", b'"x"', {}),
        ("POST", "/mcp", b"null", {}),
        ("POST", "/mcp", b"\xff\xfe", {}),
        ("POST", "/mcp", b'{"jsonrpc":"2.0","id":1,"method":"ping"}', {"Content-Length": "abc"}),
        ("POST", "/mcp", b'{"jsonrpc":"2.0","id":1,"method":"ping"}', {"Authorization": "Bearer \u00e9"}),
        ("POST", "/mcp", b'{"jsonrpc":"2.0","id":1,"method":"tools/call","params":[1]}', {}),
        ("POST", "/other", b"{}", {}),
        ("GET", "/mcp", b"", {}),
        ("PUT", "/mcp", b"{}", {}),
        ("HEAD", "/mcp", b"", {}),
        ("OPTIONS", "/mcp", b"", {}),
        ("TRACE", "/mcp", b"", {}),
        ("CONNECT", "/mcp", b"", {}),
    ]
    for method, path, body, headers in requests:
        runs += 1
        try:
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            if "Content-Length" in headers:
                conn.putrequest(method, path)
                for k, v in headers.items():
                    conn.putheader(k, v)
                conn.endheaders()
                conn.send(body)
            else:
                conn.request(method, path, body=body, headers=headers)
            resp = conn.getresponse()
            payload = resp.read()
            status = resp.status
            if method in {"PUT", "HEAD", "OPTIONS", "TRACE", "CONNECT"} and status != 405:
                bad[("http not 405", method, path, body[:15])] += 1
            if status >= 500:
                bad[("http 5xx", method, path, body[:15])] += 1
            if status == 200 and b'"code": -32000' in payload:
                bad[("http -32000", method, path, body[:15])] += 1
                ex.setdefault(("http -32000", method, path, body[:15]), payload[:120])
        except Exception as exc:
            bad[("http exception", method, path, type(exc).__name__)] += 1
    # the server must still answer afterwards
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    conn.request("POST", "/mcp", body=b'{"jsonrpc":"2.0","id":9,"method":"ping"}')
    alive = conn.getresponse().status == 200
    httpd.shutdown()
    if bad or not alive:
        for key, n in bad.most_common(40):
            print(f"FAIL {n:3} {key}  {ex.get(key, '')}")
        if not alive:
            print("FAIL the HTTP server stopped answering")
        return 1
    print(f"PASS {runs} malformed JSON-RPC and HTTP requests got specific errors; the HTTP server kept answering")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
