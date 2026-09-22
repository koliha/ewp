"""EWP MCP façade — shipped in 0.2.0.

Stdio JSON-RPC (MCP) and optional HTTP POST /mcp.

This is the policy boundary. Agents talk to these tools. They do not get
store-native write tools. Warrant is computed, never stored as truth.

Origin rule: a caller may not self-assert a trusted origin_type unless
`ingest_attestation` is true (operator/ingest channel). Otherwise the
write is refused. That is the ingest boundary SECURITY.md assumes.
"""

from __future__ import annotations

import argparse
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from .codec import view_from_dict, warrant_from_dict
from .may_act import Action, RiskPolicy, may_act
from .sqlite_adapter import SQLiteAdapter
from .types import (
    TRUSTED_ORIGINS,
    Assertion,
    EvidenceItem,
    EvidenceView,
    Policy,
    SourceRef,
    VerificationCheck,
)
from .versions import PROTOCOL
from .warrant import warrant_now

SERVER_NAME = "ewp-mcp"
PROTOCOL_VERSION = "2024-11-05"

REFUSE_PERSIST_WARRANT = "EWP_REFUSE_PERSIST_WARRANT"
REFUSE_UNATTESTED_ORIGIN = "EWP_REFUSE_UNATTESTED_TRUSTED_ORIGIN"
REFUSE_MISSING_VIEW = "EWP_REFUSE_MISSING_VIEW"
REFUSE_MAY_ACT_WITHOUT_ACTION = "EWP_REFUSE_MAY_ACT_WITHOUT_ACTION"


class McpError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _origins_in(view: EvidenceView) -> set[str]:
    found = {a.source.origin_type for a in view.assertions}
    found |= {e.source.origin_type for e in view.evidence}
    found |= {c.source.origin_type for c in view.checks}
    return found


class EwpMcp:
    def __init__(self, db_path: str = ":memory:") -> None:
        self.db_path = db_path
        self.store = SQLiteAdapter(db_path)

    def handle(self, message: dict[str, Any]) -> dict[str, Any] | None:
        if "method" not in message:
            return self._err(message.get("id"), -32600, "invalid request")
        method = message["method"]
        mid = message.get("id")
        params = message.get("params") or {}
        if mid is None and method.startswith("notifications/"):
            return None
        try:
            if method == "initialize":
                return self._ok(mid, self._initialize())
            if method == "ping":
                return self._ok(mid, {})
            if method == "tools/list":
                return self._ok(mid, {"tools": TOOLS})
            if method == "tools/call":
                return self._ok(mid, self._call_tool(params.get("name"), params.get("arguments") or {}))
            if method == "resources/list":
                return self._ok(mid, {"resources": self._resources()})
            if method == "resources/read":
                return self._ok(mid, self._read_resource(params.get("uri") or ""))
            if method == "prompts/list":
                return self._ok(mid, {"prompts": []})
            return self._err(mid, -32601, f"method not found: {method}")
        except McpError as exc:
            return self._ok(
                mid,
                {
                    "content": [{"type": "text", "text": json.dumps({"error": exc.code, "message": exc.message})}],
                    "isError": True,
                    "error": {"code": exc.code, "message": exc.message},
                },
            )
        except Exception as exc:  # noqa: BLE001 — surface to the client
            return self._err(mid, -32000, str(exc))

    def _initialize(self) -> dict[str, Any]:
        return {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {}, "resources": {}},
            "serverInfo": {"name": SERVER_NAME, "version": PROTOCOL},
            "instructions": (
                "EWP evaluates evidence. Memory is not truth. "
                "Call ewp_warrant_now; do not persist its result as evidence. "
                "Say OPEN and DEGRADED out loud. Trusted origins require ingest_attestation."
            ),
        }

    def _call_tool(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        dispatch = {
            "ewp_warrant_now": self.tool_warrant_now,
            "ewp_evidence_view_put": self.tool_view_put,
            "ewp_evidence_view_get": self.tool_view_get,
            "ewp_check_record": self.tool_check_record,
            "ewp_evidence_record": self.tool_evidence_record,
            "ewp_may_act": self.tool_may_act,
            "ewp_memory_context": self.tool_memory_context,
        }
        if name not in dispatch:
            raise McpError("EWP_UNKNOWN_TOOL", f"unknown tool {name}")
        result = dispatch[name](args)
        text = json.dumps(result, indent=2, sort_keys=True)
        return {"content": [{"type": "text", "text": text}], "structuredContent": result}

    def _require_attestation(self, args: dict[str, Any], view: EvidenceView) -> None:
        trusted = _origins_in(view) & set(TRUSTED_ORIGINS)
        if trusted and not args.get("ingest_attestation"):
            raise McpError(
                REFUSE_UNATTESTED_ORIGIN,
                "trusted origin_type values require ingest_attestation=true at the ingest boundary: "
                + ", ".join(sorted(trusted)),
            )

    def _load(self, proposition_id: str, view_id: str = "mcp") -> EvidenceView:
        try:
            return self.store.get_view(proposition_id, view_id)
        except Exception as exc:  # noqa: BLE001
            raise McpError(REFUSE_MISSING_VIEW, f"no view for {proposition_id}: {exc}") from exc

    def tool_view_put(self, args: dict[str, Any]) -> dict[str, Any]:
        if "warrant" in args and "proposition_id" in (args.get("warrant") or {}):
            raise McpError(REFUSE_PERSIST_WARRANT, "WarrantView is computed. Do not write it as evidence.")
        raw = args.get("view") or args
        if raw.get("warrant") and raw.get("evaluated_at") and "assertions" not in raw:
            raise McpError(REFUSE_PERSIST_WARRANT, "WarrantView is computed. Do not write it as evidence.")
        view = view_from_dict(raw)
        self._require_attestation(args, view)
        self.store.load_view(view)
        return {
            "stored": True,
            "proposition_id": view.proposition_id,
            "view_id": view.view_id,
            "assertions": len(view.assertions),
            "checks": len(view.checks),
        }

    def tool_view_get(self, args: dict[str, Any]) -> dict[str, Any]:
        view = self._load(str(args["proposition_id"]), str(args.get("view_id") or "mcp"))
        return view.to_dict()

    def tool_warrant_now(self, args: dict[str, Any]) -> dict[str, Any]:
        evaluated_at = str(args.get("evaluated_at") or "")
        if not evaluated_at:
            raise McpError("EWP_MISSING_EVALUATED_AT", "evaluated_at is required")
        if args.get("view"):
            view = view_from_dict(args["view"])
        else:
            view = self._load(str(args["proposition_id"]), str(args.get("view_id") or "mcp"))
        policy = Policy(
            policy_id=str(args.get("policy_id") or "reference-v1"),
            version=str(args.get("policy_version") or "reference-v1"),
        )
        result = warrant_now(view, policy, evaluated_at)
        payload = result.normative()
        payload["independent_lineage_count"] = result.independent_lineage_count
        payload["supporting_evidence_ids"] = result.supporting_evidence_ids
        payload["opposing_evidence_ids"] = result.opposing_evidence_ids
        payload["omitted_sources"] = result.omitted_sources
        payload["stale"] = result.stale
        payload["note"] = "normative axes only; strength is not an interchange field"
        return payload

    def tool_check_record(self, args: dict[str, Any]) -> dict[str, Any]:
        view = self._load(str(args["proposition_id"]), str(args.get("view_id") or "mcp"))
        check = args["check"]
        source = source_from_args(check.get("source") or {}, fallback=f"check:{check.get('check_id')}")
        built = EvidenceView(
            view_id=view.view_id,
            proposition_id=view.proposition_id,
            checks=[
                VerificationCheck(
                    check_id=str(check["check_id"]),
                    method=str(check["method"]),
                    scope=str(check.get("scope") or view.proposition_id),
                    source=source,
                    observed_at=str(check["observed_at"]),
                    result=check["result"],
                    subjects=tuple(check.get("subjects") or ()),
                )
            ],
        )
        self._require_attestation(args, built)
        view.checks.append(built.checks[0])
        self.store.load_view(view)
        return {"recorded": True, "check_id": built.checks[0].check_id, "count": len(view.checks)}

    def tool_evidence_record(self, args: dict[str, Any]) -> dict[str, Any]:
        view = self._load(str(args["proposition_id"]), str(args.get("view_id") or "mcp"))
        item = args["evidence"]
        source = source_from_args(item.get("source") or {}, fallback=str(item.get("evidence_id")))
        ev = EvidenceItem(
            evidence_id=str(item["evidence_id"]),
            proposition_id=view.proposition_id,
            polarity=item.get("polarity") or "supports",
            source=source,
            content=str(item["content"]),
            observed_at=str(item["observed_at"]),
        )
        probe = EvidenceView(view_id=view.view_id, proposition_id=view.proposition_id, evidence=[ev])
        self._require_attestation(args, probe)
        view.evidence.append(ev)
        if args.get("text"):
            view.assertions.append(
                Assertion(
                    assertion_id=str(args.get("assertion_id") or ev.evidence_id + ":a"),
                    proposition_id=view.proposition_id,
                    text=str(args["text"]),
                    asserted_by=str(args.get("asserted_by") or "mcp"),
                    assertion_confidence=float(args.get("assertion_confidence") or 0.5),
                    source=source,
                    asserted_at=ev.observed_at,
                )
            )
        self.store.load_view(view)
        return {"recorded": True, "evidence_id": ev.evidence_id, "count": len(view.evidence)}

    def tool_may_act(self, args: dict[str, Any]) -> dict[str, Any]:
        action_raw = args.get("action")
        if not action_raw:
            raise McpError(REFUSE_MAY_ACT_WITHOUT_ACTION, "may_act requires an action; it is not inferred from WarrantView")
        if args.get("warrant"):
            warrant = warrant_from_dict(args["warrant"])
        else:
            evaluated_at = str(args.get("evaluated_at") or "")
            if not evaluated_at:
                raise McpError("EWP_MISSING_EVALUATED_AT", "evaluated_at is required when warrant is omitted")
            view = self._load(str(args["proposition_id"]), str(args.get("view_id") or "mcp"))
            warrant = warrant_now(view, Policy(), evaluated_at)
        action = Action(
            action_id=str(action_raw.get("action_id") or "unnamed"),
            kind=str(action_raw.get("kind") or "unknown"),
            reversible=bool(action_raw.get("reversible", True)),
            risk=action_raw.get("risk") or "low",
        )
        rp_raw = args.get("risk_policy") or {}
        risk_policy = RiskPolicy(
            policy_id=str(rp_raw.get("policy_id") or "action-v0.1"),
            version=str(rp_raw.get("version") or "0.1.0"),
        )
        decision = may_act(warrant, action, risk_policy)
        return {
            "decision": decision,
            "proposition_id": warrant.proposition_id,
            "acceptance": warrant.warrant.acceptance,
            "conflict": warrant.warrant.conflict,
            "sufficiency": warrant.warrant.sufficiency,
        }

    def tool_memory_context(self, args: dict[str, Any]) -> dict[str, Any]:
        evaluated_at = str(args.get("evaluated_at") or "")
        if not evaluated_at:
            raise McpError("EWP_MISSING_EVALUATED_AT", "evaluated_at is required")
        view = self._load(str(args["proposition_id"]), str(args.get("view_id") or "mcp"))
        result = warrant_now(view, Policy(), evaluated_at)
        w = result.warrant
        warnings: list[str] = []
        if w.conflict == "OPEN":
            warnings.append("conflict=OPEN — say so; do not narrate a reconciliation the view does not have")
        if w.sufficiency == "DEGRADED":
            warnings.append("sufficiency=DEGRADED — the view is incomplete")
        if w.currency == "STALE":
            warnings.append("currency=STALE")
        if w.currency == "SUPERSEDED":
            warnings.append("currency=SUPERSEDED")
        if w.acceptance != "ACCEPTED":
            warnings.append(f"acceptance={w.acceptance} — fluency is not recollection")
        return {
            "proposition_id": view.proposition_id,
            "query": args.get("query"),
            "evaluated_at": evaluated_at,
            "warrant": result.normative()["warrant"],
            "supporting_evidence_ids": result.supporting_evidence_ids,
            "opposing_evidence_ids": result.opposing_evidence_ids,
            "omitted_sources": result.omitted_sources,
            "checks": result.checks,
            "independent_lineage_count": result.independent_lineage_count,
            "warnings": warnings,
            "persona": None,
            "note": "persona briefing is not shipped; axes plus warnings are the packet",
        }

    def _resources(self) -> list[dict[str, Any]]:
        return [
            {
                "uri": "ewp://protocol",
                "name": "EWP protocol identity",
                "mimeType": "application/json",
            }
        ]

    def _read_resource(self, uri: str) -> dict[str, Any]:
        parsed = urlparse(uri)
        if uri == "ewp://protocol" or parsed.netloc == "protocol":
            body = json.dumps({"protocol": PROTOCOL, "policy": "reference-v1", "mcp": SERVER_NAME})
            return {"contents": [{"uri": uri, "mimeType": "application/json", "text": body}]}
        if parsed.netloc == "proposition":
            parts = [p for p in parsed.path.split("/") if p]
            if not parts:
                raise McpError(REFUSE_MISSING_VIEW, "proposition id required")
            pid = parts[0]
            qs = parse_qs(parsed.query)
            if parts[-1] == "warrant" or qs.get("kind") == ["warrant"]:
                evaluated_at = (qs.get("evaluated_at") or [""])[0]
                result = self.tool_warrant_now({"proposition_id": pid, "evaluated_at": evaluated_at})
                text = json.dumps(result)
            else:
                text = json.dumps(self.tool_view_get({"proposition_id": pid}))
            return {"contents": [{"uri": uri, "mimeType": "application/json", "text": text}]}
        raise McpError("EWP_UNKNOWN_RESOURCE", uri)

    @staticmethod
    def _ok(mid: Any, result: Any) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": mid, "result": result}

    @staticmethod
    def _err(mid: Any, code: int, message: str) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": message}}


def source_from_args(d: dict[str, Any], fallback: str) -> SourceRef:
    sid = str(d.get("source_id") or fallback)
    return SourceRef(
        source_id=sid,
        lineage_id=str(d.get("lineage_id") or sid),
        origin_type=str(d.get("origin_type") or "extract"),
        origin_locator=str(d.get("origin_locator") or f"mcp:{sid}"),
        snapshot_id=str(d.get("snapshot_id") or sid),
        content_hash=str(d.get("content_hash") or f"mcp:{sid}"),
        observed_at=str(d.get("observed_at") or "1970-01-01T00:00:00+00:00"),
        extractor_id=d.get("extractor_id"),
        parent_source_id=d.get("parent_source_id"),
    )


TOOLS = [
    {
        "name": "ewp_warrant_now",
        "description": "Evaluate an EvidenceView (inline or stored) at evaluated_at. Returns the five normative axes. Does not persist warrant.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "evaluated_at": {"type": "string"},
                "proposition_id": {"type": "string"},
                "view_id": {"type": "string"},
                "view": {"type": "object"},
                "policy_id": {"type": "string"},
                "policy_version": {"type": "string"},
            },
            "required": ["evaluated_at"],
        },
    },
    {
        "name": "ewp_evidence_view_put",
        "description": "Persist an EvidenceView. Refuses WarrantView bodies. Trusted origins require ingest_attestation=true.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "view": {"type": "object"},
                "ingest_attestation": {"type": "boolean"},
            },
            "required": ["view"],
        },
    },
    {
        "name": "ewp_evidence_view_get",
        "description": "Load a stored EvidenceView by proposition_id.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "proposition_id": {"type": "string"},
                "view_id": {"type": "string"},
            },
            "required": ["proposition_id"],
        },
    },
    {
        "name": "ewp_check_record",
        "description": "Append a VerificationCheck to a stored view. Trusted origin requires ingest_attestation.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "proposition_id": {"type": "string"},
                "view_id": {"type": "string"},
                "check": {"type": "object"},
                "ingest_attestation": {"type": "boolean"},
            },
            "required": ["proposition_id", "check"],
        },
    },
    {
        "name": "ewp_evidence_record",
        "description": "Append an EvidenceItem to a stored view.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "proposition_id": {"type": "string"},
                "evidence": {"type": "object"},
                "text": {"type": "string"},
                "ingest_attestation": {"type": "boolean"},
            },
            "required": ["proposition_id", "evidence"],
        },
    },
    {
        "name": "ewp_may_act",
        "description": "Separate action gate. Requires an action object. Will not infer permission from WarrantView alone.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {"type": "object"},
                "warrant": {"type": "object"},
                "proposition_id": {"type": "string"},
                "evaluated_at": {"type": "string"},
                "risk_policy": {"type": "object"},
            },
            "required": ["action"],
        },
    },
    {
        "name": "ewp_memory_context",
        "description": "Bounded packet: axes, evidence ids, warnings. Not a persona biography. OPEN and DEGRADED are explicit.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "proposition_id": {"type": "string"},
                "evaluated_at": {"type": "string"},
                "query": {"type": "string"},
                "view_id": {"type": "string"},
            },
            "required": ["proposition_id", "evaluated_at"],
        },
    },
]


def serve_stdio(server: EwpMcp) -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}}) + "\n")
            sys.stdout.flush()
            continue
        reply = server.handle(message)
        if reply is not None:
            sys.stdout.write(json.dumps(reply) + "\n")
            sys.stdout.flush()


def serve_http(server: EwpMcp, host: str, port: int) -> None:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args: Any) -> None:
            sys.stderr.write("ewp-mcp " + (fmt % args) + "\n")

        def _write(self, code: int, payload: dict[str, Any]) -> None:
            body = json.dumps(payload).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self) -> None:  # noqa: N802
            if self.path not in {"/mcp", "/", "/mcp/"}:
                self._write(404, {"error": "not found"})
                return
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length)
            try:
                message = json.loads(raw.decode() or "{}")
            except json.JSONDecodeError:
                self._write(400, {"jsonrpc": "2.0", "error": {"code": -32700, "message": "parse error"}})
                return
            reply = server.handle(message) or {"jsonrpc": "2.0", "result": None}
            self._write(200, reply)

        def do_GET(self) -> None:  # noqa: N802
            if self.path in {"/health", "/"}:
                self._write(200, {"server": SERVER_NAME, "protocol": PROTOCOL})
                return
            self._write(404, {"error": "not found"})

    httpd = ThreadingHTTPServer((host, port), Handler)
    sys.stderr.write(f"ewp-mcp http://{host}:{port}/mcp  db={server.db_path}\n")
    httpd.serve_forever()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ewp-mcp", description="EWP MCP façade")
    parser.add_argument("--db", default=":memory:", help="SQLite path, default memory")
    parser.add_argument("--http", default="", help="host:port for JSON-RPC HTTP (optional)")
    parser.add_argument("--stdio", action="store_true", help="JSON-RPC on stdin/stdout (default if no --http)")
    args = parser.parse_args(argv)
    if args.db != ":memory:":
        Path(args.db).parent.mkdir(parents=True, exist_ok=True)
    server = EwpMcp(args.db)
    if args.http:
        host, _, port = args.http.partition(":")
        serve_http(server, host or "127.0.0.1", int(port or "8765"))
        return 0
    serve_stdio(server)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
