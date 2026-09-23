"""EWP MCP façade — shipped in 0.2.0.

Stdio is MCP's stdio transport: newline-delimited JSON-RPC 2.0, one message
per line, no embedded newlines, no header framing. HTTP POST /mcp is plain
JSON-RPC for OpenClaw-style clients. It is not MCP Streamable HTTP.

This is the policy boundary. Agents talk to these tools. They do not get
store-native write tools. Warrant is computed, never stored as truth.

Every write requires a server-side ingest role: --allow-ingest on stdio,
or the ingest token (EWP_INGEST_TOKEN / --ingest-token-file) on HTTP.
Without it the server is evaluate-only. Trusted origin_type values also
require ingest_attestation=true on the call; that flag is a declaration,
not authentication.

Inline EvidenceViews are hypothetical. ewp_warrant_now demotes their
trusted origins unless the caller holds the ingest role; ewp_may_act
refuses them. may_act evaluates at the server clock.
"""

from __future__ import annotations

import argparse
import contextvars
import dataclasses
import hmac
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse

from .classify import InvalidEvidenceView, check_verification_class, parse_ts
from .codec import subjects_from, view_from_dict
from .may_act import RISK_LEVELS, Action, RiskPolicy, may_act
from .sqlite_adapter import ImmutableRecordError, LedgerError, MissingViewError, SQLiteAdapter
from .types import (
    TRUSTED_ORIGINS,
    Assertion,
    EvidenceItem,
    EvidenceView,
    Policy,
    SourceRef,
    VerificationCheck,
)
from .versions import POLICY, PROTOCOL
from .warrant import warrant_now

SERVER_NAME = "ewp-mcp"
# MCP protocol revisions this server speaks. The client's requested
# revision is echoed when supported; otherwise the first entry is offered.
SUPPORTED_PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
MAX_HTTP_BODY = 1 << 20
DEFAULT_MAX_CLOCK_SKEW_SECONDS = 300
INLINE_ORIGIN_PREFIX = "inline:"
_REQUEST_INGEST = contextvars.ContextVar("ewp_request_ingest", default=False)

REFUSE_PERSIST_WARRANT = "EWP_REFUSE_PERSIST_WARRANT"
REFUSE_UNATTESTED_ORIGIN = "EWP_REFUSE_UNATTESTED_TRUSTED_ORIGIN"
REFUSE_MISSING_VIEW = "EWP_REFUSE_MISSING_VIEW"
REFUSE_MAY_ACT_WITHOUT_ACTION = "EWP_REFUSE_MAY_ACT_WITHOUT_ACTION"
REFUSE_CLIENT_WARRANT = "EWP_REFUSE_CLIENT_SUPPLIED_WARRANT"
REFUSE_INGEST_ROLE = "EWP_REFUSE_INGEST_ROLE"
REFUSE_MISSING_CONTENT_HASH = "EWP_REFUSE_MISSING_CONTENT_HASH"
REFUSE_MISSING_OBSERVED_AT = "EWP_REFUSE_MISSING_OBSERVED_AT"
REFUSE_INLINE_VIEW = "EWP_REFUSE_INLINE_VIEW_FOR_ACTION"
REFUSE_EVALUATED_AT_SKEW = "EWP_REFUSE_EVALUATED_AT_SKEW"
REFUSE_CLIENT_RISK_POLICY = "EWP_REFUSE_CLIENT_RISK_POLICY"
REFUSE_INVALID_ACTION = "EWP_REFUSE_INVALID_ACTION"
REFUSE_INVALID_VIEW = "EWP_REFUSE_INVALID_EVIDENCE_VIEW"
REFUSE_IMMUTABLE_RECORD = "EWP_REFUSE_IMMUTABLE_RECORD"
REFUSE_INVALID_ARGUMENTS = "EWP_REFUSE_INVALID_ARGUMENTS"
REFUSE_LEDGER = "EWP_REFUSE_LEDGER_UNAVAILABLE"

# JSON-RPC error codes for non-tool methods (MCP: resource not found is -32002).
_RPC_CODES = {"EWP_UNKNOWN_RESOURCE": -32002, REFUSE_MISSING_VIEW: -32002}


def encode_mcp_message(payload: dict[str, Any]) -> bytes:
    """One JSON-RPC message per line. json.dumps escapes embedded newlines."""
    return (json.dumps(payload, separators=(",", ":")) + "\n").encode("utf-8")


def read_mcp_message(buf) -> dict[str, Any] | None:
    """Read one newline-delimited JSON-RPC message. None at EOF.

    Blank lines are skipped. Raises json.JSONDecodeError on a bad line.
    """
    while True:
        line = buf.readline()
        if not line:
            return None
        text = line.decode("utf-8").strip()
        if text:
            return json.loads(text)


class McpError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _origins_in(view: EvidenceView) -> set[str]:
    found = {a.source.origin_type for a in view.assertions}
    found |= {e.source.origin_type for e in view.evidence}
    found |= {c.source.origin_type for c in view.checks}
    return found


def _demote_source(s: SourceRef) -> SourceRef:
    if s.origin_type in TRUSTED_ORIGINS:
        return dataclasses.replace(s, origin_type=INLINE_ORIGIN_PREFIX + s.origin_type)
    return s


def demote_inline_origins(view: EvidenceView) -> EvidenceView:
    """A caller-built view cannot carry trusted provenance it has not been
    granted. Trusted origins become `inline:<origin>`, which is untrusted."""
    return dataclasses.replace(
        view,
        assertions=[dataclasses.replace(a, source=_demote_source(a.source)) for a in view.assertions],
        evidence=[dataclasses.replace(e, source=_demote_source(e.source)) for e in view.evidence],
        checks=[dataclasses.replace(c, source=_demote_source(c.source)) for c in view.checks],
    )


class EwpMcp:
    def __init__(
        self,
        db_path: str = ":memory:",
        *,
        ingest_enabled: bool = False,
        ingest_token: str = "",
        clock: Callable[[], str] = _utc_now,
        max_clock_skew_seconds: int = DEFAULT_MAX_CLOCK_SKEW_SECONDS,
    ) -> None:
        self.db_path = db_path
        # A server that can never write opens its ledger read-only: a mistyped
        # path is an error, not a new empty ledger, and the handle cannot write.
        self.read_only = not ingest_enabled and not ingest_token and db_path != ":memory:"
        self.store = SQLiteAdapter(db_path, read_only=self.read_only)
        self.ingest_enabled = ingest_enabled
        self.ingest_token = ingest_token
        self.clock = clock
        self.max_clock_skew_seconds = max_clock_skew_seconds

    def handle(self, message: dict[str, Any]) -> dict[str, Any] | None:
        if not isinstance(message, dict) or "method" not in message:
            mid = message.get("id") if isinstance(message, dict) else None
            return self._err(mid, -32600, "invalid request")
        method = message["method"]
        if "id" not in message:
            # JSON-RPC notification: never answered.
            return None
        mid = message["id"]
        if mid is None:
            # MCP: request ids must not be null. Answer rather than leave the client waiting.
            return self._err(None, -32600, "invalid request: id must not be null")
        params = message.get("params") or {}
        try:
            if method == "initialize":
                return self._ok(mid, self._initialize(params))
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
            if method == "resources/templates/list":
                return self._ok(mid, {"resourceTemplates": RESOURCE_TEMPLATES})
            if method == "prompts/list":
                return self._ok(mid, {"prompts": []})
            return self._err(mid, -32601, f"method not found: {method}")
        except McpError as exc:
            # Tool failures are returned inside tools/call results (see _call_tool).
            # Anything reaching here came from another method: a JSON-RPC error.
            return {
                "jsonrpc": "2.0",
                "id": mid,
                "error": {"code": _RPC_CODES.get(exc.code, -32602), "message": exc.message, "data": {"ewp_code": exc.code}},
            }
        except Exception as exc:  # noqa: BLE001 — surface to the client
            return self._err(mid, -32000, str(exc))

    def _initialize(self, params: dict[str, Any]) -> dict[str, Any]:
        requested = params.get("protocolVersion")
        version = requested if requested in SUPPORTED_PROTOCOL_VERSIONS else SUPPORTED_PROTOCOL_VERSIONS[0]
        return {
            "protocolVersion": version,
            "capabilities": {"tools": {}, "resources": {}},
            "serverInfo": {"name": SERVER_NAME, "version": PROTOCOL},
            "instructions": (
                "EWP evaluates evidence. Memory is not truth. "
                "Find claims with ewp_list_propositions, then call ewp_memory_context before relying on one. "
                "Do not persist warrant as evidence. "
                "Say OPEN and DEGRADED out loud. Writes require the server-side ingest role."
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
            "ewp_list_propositions": self.tool_list_propositions,
        }
        try:
            if name not in dispatch:
                raise McpError("EWP_UNKNOWN_TOOL", f"unknown tool {name}")
            try:
                result = dispatch[name](args)
            except McpError:
                raise
            except InvalidEvidenceView as exc:
                raise McpError(REFUSE_INVALID_VIEW, str(exc)) from exc
            except ImmutableRecordError as exc:
                raise McpError(REFUSE_IMMUTABLE_RECORD, str(exc)) from exc
            except MissingViewError as exc:
                raise McpError(REFUSE_MISSING_VIEW, str(exc.args[0] if exc.args else exc)) from exc
            except (sqlite3.Error, LedgerError) as exc:
                raise McpError(REFUSE_LEDGER, f"ledger error: {exc}") from exc
            except KeyError as exc:
                raise McpError(REFUSE_INVALID_ARGUMENTS, f"missing required argument {exc}") from exc
            except (TypeError, ValueError, AttributeError) as exc:
                raise McpError(REFUSE_INVALID_ARGUMENTS, str(exc)) from exc
        except McpError as exc:
            return {
                "content": [{"type": "text", "text": json.dumps({"error": exc.code, "message": exc.message})}],
                "isError": True,
                "error": {"code": exc.code, "message": exc.message},
            }
        text = json.dumps(result, indent=2, sort_keys=True)
        return {"content": [{"type": "text", "text": text}], "structuredContent": result}

    # -- roles ------------------------------------------------------------

    def _has_ingest_role(self) -> bool:
        return self.ingest_enabled or _REQUEST_INGEST.get()

    def _require_role(self) -> None:
        """Checked first on every write tool, before the payload is examined."""
        if not self._has_ingest_role():
            raise McpError(
                REFUSE_INGEST_ROLE,
                "writes require a server-side ingest role (--allow-ingest on stdio, "
                "or the ingest token on HTTP). Without it this server is evaluate-only.",
            )

    def _require_write(self, args: dict[str, Any], view: EvidenceView) -> None:
        """Every mutation needs the ingest role. Trusted origins also need
        the caller to declare ingest_attestation=true."""
        self._require_role()
        trusted = _origins_in(view) & set(TRUSTED_ORIGINS)
        if trusted and not args.get("ingest_attestation"):
            raise McpError(
                REFUSE_UNATTESTED_ORIGIN,
                "trusted origin_type values require ingest_attestation=true at the ingest boundary: "
                + ", ".join(sorted(trusted)),
            )

    def _server_time(self, args: dict[str, Any]) -> str:
        """Live decisions use the server clock. A caller-supplied T must be
        within the allowed skew of it."""
        now = self.clock()
        supplied = args.get("evaluated_at")
        if not supplied:
            return now
        try:
            skew = abs((parse_ts(str(supplied)) - parse_ts(now)).total_seconds())
        except ValueError as exc:
            raise McpError(REFUSE_EVALUATED_AT_SKEW, f"unparsable evaluated_at {supplied!r}") from exc
        if skew > self.max_clock_skew_seconds:
            raise McpError(
                REFUSE_EVALUATED_AT_SKEW,
                f"evaluated_at {supplied} is {int(skew)}s from server time {now}; "
                f"live gates allow {self.max_clock_skew_seconds}s. Use ewp_warrant_now to replay a past T.",
            )
        return str(supplied)

    def _load(self, args: dict[str, Any]) -> EvidenceView:
        """The requested snapshot, or the latest one for the proposition."""
        pid = str(args["proposition_id"])
        view_id = args.get("view_id") or None
        try:
            return self.store.get_view(pid, None if view_id is None else str(view_id))
        except MissingViewError as exc:
            raise McpError(REFUSE_MISSING_VIEW, str(exc.args[0] if exc.args else exc)) from exc

    # -- tools ------------------------------------------------------------

    def tool_view_put(self, args: dict[str, Any]) -> dict[str, Any]:
        self._require_role()
        if "warrant" in args and "proposition_id" in (args.get("warrant") or {}):
            raise McpError(REFUSE_PERSIST_WARRANT, "WarrantView is computed. Do not write it as evidence.")
        raw = args.get("view") or args
        if raw.get("warrant") and raw.get("evaluated_at") and "assertions" not in raw:
            raise McpError(REFUSE_PERSIST_WARRANT, "WarrantView is computed. Do not write it as evidence.")
        view = view_from_dict(raw)
        self._require_write(args, view)
        self.store.load_view(view)
        return {
            "stored": True,
            "proposition_id": view.proposition_id,
            "view_id": view.view_id,
            "assertions": len(view.assertions),
            "checks": len(view.checks),
        }

    def tool_view_get(self, args: dict[str, Any]) -> dict[str, Any]:
        return self._load(args).to_dict()

    def tool_warrant_now(self, args: dict[str, Any]) -> dict[str, Any]:
        evaluated_at = str(args.get("evaluated_at") or "")
        if not evaluated_at:
            raise McpError("EWP_MISSING_EVALUATED_AT", "evaluated_at is required")
        demoted: list[str] = []
        if args.get("view"):
            view = view_from_dict(args["view"])
            if not (self._has_ingest_role() and args.get("ingest_attestation")):
                demoted = sorted(_origins_in(view) & set(TRUSTED_ORIGINS))
                view = demote_inline_origins(view)
        else:
            view = self._load(args)
        policy = Policy(
            policy_id=str(args.get("policy_id") or POLICY),
            version=str(args.get("policy_version") or POLICY),
        )
        result = warrant_now(view, policy, evaluated_at)
        payload = result.normative()
        payload["independent_lineage_count"] = result.independent_lineage_count
        payload["supporting_evidence_ids"] = result.supporting_evidence_ids
        payload["opposing_evidence_ids"] = result.opposing_evidence_ids
        payload["omitted_sources"] = result.omitted_sources
        payload["stale"] = result.stale
        payload["rationale_codes"] = sorted(result.warrant.rationale_codes)
        if demoted:
            payload["inline_origins_demoted"] = demoted
        payload["note"] = "normative: identity, time, five axes. rationale_codes and strength are diagnostic"
        return payload

    def _build_source(self, raw: dict[str, Any], fallback: str) -> SourceRef:
        return source_from_args(raw or {}, fallback=fallback)

    def tool_check_record(self, args: dict[str, Any]) -> dict[str, Any]:
        """Append a check: a new snapshot = latest snapshot + this check."""
        self._require_role()
        pid = str(args["proposition_id"])
        check = args["check"]
        source = self._build_source(check.get("source"), fallback=f"check:{check.get('check_id')}")
        built = VerificationCheck(
            check_id=str(check["check_id"]),
            method=str(check["method"]),
            scope=str(check.get("scope") or pid),
            source=source,
            observed_at=str(check["observed_at"]),
            result=check["result"],
            subjects=subjects_from(check.get("subjects")),
        )
        self._require_write(args, EvidenceView(view_id="probe", proposition_id=pid, checks=[built]))
        view = self.store.extend_view(pid, checks=[built], new_view_id=args.get("new_view_id") or None)
        return {"recorded": True, "check_id": built.check_id, "view_id": view.view_id, "count": len(view.checks)}

    def tool_evidence_record(self, args: dict[str, Any]) -> dict[str, Any]:
        """Append evidence (and optional assertion text): a new snapshot."""
        self._require_role()
        pid = str(args["proposition_id"])
        item = args["evidence"]
        if "polarity" not in item:
            raise McpError(REFUSE_INVALID_ARGUMENTS, "evidence.polarity is required (supports|opposes); it is never assumed")
        source = self._build_source(item.get("source"), fallback=str(item.get("evidence_id")))
        ev = EvidenceItem(
            evidence_id=str(item["evidence_id"]),
            proposition_id=pid,
            polarity=item["polarity"],
            source=source,
            content=str(item["content"]),
            observed_at=str(item["observed_at"]),
        )
        assertions: list[Assertion] = []
        if args.get("text"):
            confidence = args.get("assertion_confidence")
            assertions.append(
                Assertion(
                    assertion_id=str(args.get("assertion_id") or ev.evidence_id + ":a"),
                    proposition_id=pid,
                    text=str(args["text"]),
                    asserted_by=str(args.get("asserted_by") or "mcp"),
                    assertion_confidence=0.5 if confidence is None else float(confidence),
                    source=source,
                    asserted_at=ev.observed_at,
                )
            )
        self._require_write(args, EvidenceView(view_id="probe", proposition_id=pid, evidence=[ev]))
        view = self.store.extend_view(
            pid, evidence=[ev], assertions=assertions, new_view_id=args.get("new_view_id") or None
        )
        return {"recorded": True, "evidence_id": ev.evidence_id, "view_id": view.view_id, "count": len(view.evidence)}

    def _action_from(self, raw: dict[str, Any]) -> Action:
        risk = raw.get("risk")
        reversible = raw.get("reversible")
        if risk not in RISK_LEVELS:
            raise McpError(REFUSE_INVALID_ACTION, f"action.risk must be one of {sorted(RISK_LEVELS)}; got {risk!r}")
        if not isinstance(reversible, bool):
            raise McpError(REFUSE_INVALID_ACTION, f"action.reversible must be a boolean; got {reversible!r}")
        return Action(
            action_id=str(raw.get("action_id") or "unnamed"),
            kind=str(raw.get("kind") or "unknown"),
            reversible=reversible,
            risk=risk,
        )

    def _risk_policy_from(self, raw: dict[str, Any] | None) -> RiskPolicy:
        """The action policy belongs to the operator, not the agent being gated."""
        if not raw:
            return RiskPolicy()
        if not self._has_ingest_role():
            raise McpError(
                REFUSE_CLIENT_RISK_POLICY,
                "risk_policy can only be set by a caller holding the ingest role",
            )
        default = RiskPolicy()
        flags = {}
        for name in ("high_requires_accepted", "high_requires_no_open_conflict"):
            value = raw.get(name, getattr(default, name))
            if not isinstance(value, bool):
                raise McpError(REFUSE_CLIENT_RISK_POLICY, f"risk_policy.{name} must be a boolean")
            flags[name] = value
        return RiskPolicy(
            policy_id=str(raw.get("policy_id") or default.policy_id),
            version=str(raw.get("version") or default.version),
            **flags,
        )

    def tool_may_act(self, args: dict[str, Any]) -> dict[str, Any]:
        action_raw = args.get("action")
        if not action_raw:
            raise McpError(REFUSE_MAY_ACT_WITHOUT_ACTION, "may_act requires an action; it is not inferred from WarrantView")
        if args.get("warrant"):
            raise McpError(
                REFUSE_CLIENT_WARRANT,
                "ewp_may_act does not accept a caller-built WarrantView; it evaluates the stored view",
            )
        if args.get("view"):
            raise McpError(
                REFUSE_INLINE_VIEW,
                "ewp_may_act evaluates stored evidence only; a caller-built EvidenceView cannot authorize action",
            )
        action = self._action_from(action_raw)
        risk_policy = self._risk_policy_from(args.get("risk_policy"))
        evaluated_at = self._server_time(args)
        view = self._load(args)
        warrant = warrant_now(view, Policy(), evaluated_at)
        decision = may_act(warrant, action, risk_policy)
        return {
            "decision": decision,
            "proposition_id": warrant.proposition_id,
            "evaluated_at": evaluated_at,
            "acceptance": warrant.warrant.acceptance,
            "conflict": warrant.warrant.conflict,
            "currency": warrant.warrant.currency,
            "sufficiency": warrant.warrant.sufficiency,
            "risk_policy": {"policy_id": risk_policy.policy_id, "version": risk_policy.version},
        }

    def tool_list_propositions(self, args: dict[str, Any]) -> dict[str, Any]:
        """Discovery: which propositions exist. Says nothing about warrant."""
        limit = args.get("limit", 50)
        if type(limit) is not int or not 1 <= limit <= 500:
            raise McpError(REFUSE_INVALID_ARGUMENTS, "limit must be an integer from 1 to 500")
        query = args.get("query")
        return {
            "propositions": self.store.list_propositions(None if query is None else str(query), limit),
            "note": "discovery only; call ewp_memory_context or ewp_warrant_now before relying on any of these",
        }

    def tool_memory_context(self, args: dict[str, Any]) -> dict[str, Any]:
        evaluated_at = str(args.get("evaluated_at") or self.clock())
        view = self._load(args)
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
        opposing = sorted({
            check_verification_class(c, view, evaluated_at)
            for c in view.checks
            if c.result == "opposes" and check_verification_class(c, view, evaluated_at) in {"EXTERNAL", "HUMAN"}
        })
        if opposing:
            warnings.append(
                f"a trusted {'/'.join(opposing)} check OPPOSES this claim — verification={w.verification} is the "
                "strongest check's class, not a confirmation"
            )
        if w.acceptance != "ACCEPTED":
            warnings.append(f"acceptance={w.acceptance} — fluency is not recollection")
        return {
            "proposition_id": view.proposition_id,
            "view_id": view.view_id,
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
            body = json.dumps({"protocol": PROTOCOL, "policy": POLICY, "mcp": SERVER_NAME})
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
    if not d.get("content_hash"):
        raise McpError(REFUSE_MISSING_CONTENT_HASH, "source.content_hash is required; the server will not invent one")
    if not d.get("observed_at"):
        raise McpError(REFUSE_MISSING_OBSERVED_AT, "source.observed_at is required; the server will not invent epoch")
    return SourceRef(
        source_id=sid,
        lineage_id=str(d.get("lineage_id") or sid),
        origin_type=str(d.get("origin_type") or "extract"),
        origin_locator=str(d.get("origin_locator") or f"mcp:{sid}"),
        snapshot_id=str(d.get("snapshot_id") or sid),
        content_hash=str(d["content_hash"]),
        observed_at=str(d["observed_at"]),
        extractor_id=d.get("extractor_id"),
        parent_source_id=d.get("parent_source_id"),
    )


RESOURCE_TEMPLATES = [
    {
        "uriTemplate": "ewp://proposition/{proposition_id}",
        "name": "Stored EvidenceView",
        "description": "The latest stored snapshot for a proposition.",
        "mimeType": "application/json",
    },
    {
        "uriTemplate": "ewp://proposition/{proposition_id}/warrant?evaluated_at={evaluated_at}",
        "name": "Normative warrant",
        "description": "The five axes for the latest snapshot at evaluated_at.",
        "mimeType": "application/json",
    },
]


TOOLS = [
    {
        "name": "ewp_warrant_now",
        "description": (
            "Evaluate a stored EvidenceView (or a hypothetical inline one) at evaluated_at. "
            "Returns the five normative axes. Inline views have trusted origins demoted unless the "
            "caller holds the ingest role and sets ingest_attestation. Does not persist warrant."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "evaluated_at": {"type": "string"},
                "proposition_id": {"type": "string"},
                "view_id": {"type": "string"},
                "view": {"type": "object"},
                "policy_id": {"type": "string"},
                "policy_version": {"type": "string"},
                "ingest_attestation": {"type": "boolean"},
            },
            "required": ["evaluated_at"],
        },
    },
    {
        "name": "ewp_evidence_view_put",
        "description": "Persist an EvidenceView. Requires the ingest role. Refuses WarrantView bodies. Trusted origins require ingest_attestation=true.",
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
        "description": "Load a stored EvidenceView snapshot by proposition_id (latest snapshot unless view_id is given).",
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
        "description": "Append a VerificationCheck: creates a new snapshot from the latest one. Requires the ingest role. Trusted origin requires ingest_attestation. Returns the new view_id.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "proposition_id": {"type": "string"},
                "new_view_id": {"type": "string", "description": "optional; content-derived when omitted"},
                "check": {"type": "object"},
                "ingest_attestation": {"type": "boolean"},
            },
            "required": ["proposition_id", "check"],
        },
    },
    {
        "name": "ewp_evidence_record",
        "description": "Append an EvidenceItem (polarity required): creates a new snapshot from the latest one. Requires the ingest role. Returns the new view_id.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "proposition_id": {"type": "string"},
                "new_view_id": {"type": "string", "description": "optional; content-derived when omitted"},
                "evidence": {
                    "type": "object",
                    "properties": {"polarity": {"type": "string", "enum": ["supports", "opposes"]}},
                    "required": ["evidence_id", "polarity", "content", "observed_at", "source"],
                },
                "text": {"type": "string"},
                "ingest_attestation": {"type": "boolean"},
            },
            "required": ["proposition_id", "evidence"],
        },
    },
    {
        "name": "ewp_may_act",
        "description": (
            "Separate action gate over the stored view at server time. Requires an action with "
            "risk (low|medium|high) and reversible (boolean). Refuses inline views and caller-built "
            "WarrantViews. risk_policy is operator-only (ingest role)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "object",
                    "properties": {
                        "action_id": {"type": "string"},
                        "kind": {"type": "string"},
                        "risk": {"type": "string", "enum": ["low", "medium", "high"]},
                        "reversible": {"type": "boolean"},
                    },
                    "required": ["risk", "reversible"],
                },
                "proposition_id": {"type": "string"},
                "view_id": {"type": "string"},
                "evaluated_at": {"type": "string", "description": "optional; must be within the server's clock skew"},
                "risk_policy": {"type": "object"},
            },
            "required": ["action", "proposition_id"],
        },
    },
    {
        "name": "ewp_list_propositions",
        "description": (
            "Find stored propositions by id or assertion text (case-insensitive substring). "
            "Returns ids, latest snapshot ids, and assertion texts. Discovery only: it does not say "
            "what is warranted; call ewp_memory_context next."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 500},
            },
        },
    },
    {
        "name": "ewp_memory_context",
        "description": "Bounded packet: axes, evidence ids, warnings. Not a persona biography. OPEN and DEGRADED are explicit. evaluated_at defaults to server time.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "proposition_id": {"type": "string"},
                "evaluated_at": {"type": "string"},
                "query": {"type": "string"},
                "view_id": {"type": "string"},
            },
            "required": ["proposition_id"],
        },
    },
]


def serve_stdio(server: EwpMcp) -> None:
    stdin = sys.stdin.buffer
    stdout = sys.stdout.buffer
    while True:
        try:
            message = read_mcp_message(stdin)
        except (json.JSONDecodeError, UnicodeDecodeError):
            stdout.write(encode_mcp_message({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}}))
            stdout.flush()
            continue
        if message is None:
            return
        reply = server.handle(message)
        if reply is not None:
            stdout.write(encode_mcp_message(reply))
            stdout.flush()


def serve_http(server: EwpMcp, host: str, port: int) -> None:
    httpd = make_http_server(server, host, port)
    role = "ingest token set" if server.ingest_token else "evaluate-only (no ingest token)"
    sys.stderr.write(f"ewp-mcp http://{host}:{httpd.server_address[1]}/mcp  db={server.db_path}  {role}\n")
    httpd.serve_forever()


def make_http_server(server: EwpMcp, host: str, port: int) -> ThreadingHTTPServer:
    if server.ingest_enabled:
        raise ValueError("--allow-ingest grants every caller the ingest role; it is stdio-only. Use the ingest token on HTTP.")

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args: Any) -> None:
            sys.stderr.write("ewp-mcp " + (fmt % args) + "\n")

        def _write(self, code: int, payload: dict[str, Any], *, close: bool = False) -> None:
            body = json.dumps(payload).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            if close:
                self.send_header("Connection", "close")
                self.close_connection = True
            self.end_headers()
            self.wfile.write(body)

        def _token_ok(self) -> bool:
            if not server.ingest_token:
                return False
            auth = self.headers.get("Authorization") or self.headers.get("X-EWP-Ingest-Token") or ""
            if auth.lower().startswith("bearer "):
                auth = auth[7:].strip()
            return hmac.compare_digest(auth.encode(), server.ingest_token.encode())

        def do_POST(self) -> None:  # noqa: N802
            if self.path not in {"/mcp", "/", "/mcp/"}:
                self._write(404, {"error": "not found"})
                return
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                self._write(400, {"jsonrpc": "2.0", "error": {"code": -32600, "message": "bad Content-Length"}})
                return
            if length < 0 or length > MAX_HTTP_BODY:
                # Do not read an oversized body; answer and drop the connection.
                self._write(413, {"jsonrpc": "2.0", "error": {"code": -32600, "message": f"body exceeds {MAX_HTTP_BODY} bytes"}}, close=True)
                return
            raw = self.rfile.read(length)
            try:
                message = json.loads(raw.decode() or "{}")
            except (json.JSONDecodeError, UnicodeDecodeError):
                self._write(400, {"jsonrpc": "2.0", "error": {"code": -32700, "message": "parse error"}})
                return
            token = _REQUEST_INGEST.set(self._token_ok())
            try:
                reply = server.handle(message)
            finally:
                _REQUEST_INGEST.reset(token)
            if reply is None:
                self.send_response(202)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            self._write(200, reply)

        def do_GET(self) -> None:  # noqa: N802
            if self.path in {"/health", "/"}:
                self._write(200, {"server": SERVER_NAME, "protocol": PROTOCOL})
                return
            self._write(404, {"error": "not found"})

    return ThreadingHTTPServer((host, port), Handler)


def _read_token(path: str) -> str:
    if path:
        return Path(path).read_text(encoding="utf-8").strip()
    return os.environ.get("EWP_INGEST_TOKEN", "").strip()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ewp-mcp", description="EWP MCP façade")
    parser.add_argument("--db", default=":memory:", help="SQLite path, default memory")
    parser.add_argument("--http", default="", help="host:port for plain JSON-RPC over HTTP (not MCP Streamable HTTP)")
    parser.add_argument("--stdio", action="store_true", help="MCP stdio transport (default if no --http)")
    parser.add_argument("--allow-ingest", action="store_true", help="stdio only: this process holds the ingest role")
    parser.add_argument(
        "--ingest-token-file",
        default="",
        help="HTTP: file holding the bearer token that grants the ingest role (default: $EWP_INGEST_TOKEN)",
    )
    args = parser.parse_args(argv)
    if args.http and args.allow_ingest:
        parser.error("--allow-ingest is stdio-only; on HTTP use --ingest-token-file or EWP_INGEST_TOKEN")
    token = _read_token(args.ingest_token_file) if args.http else ""
    can_write = bool(args.allow_ingest or token)
    if args.db == ":memory:" and not can_write:
        parser.error("--db is required: the read-only server evaluates an existing ledger (create one with ewp-ingest)")
    if can_write and args.db != ":memory:":
        Path(args.db).parent.mkdir(parents=True, exist_ok=True)
    try:
        server = EwpMcp(args.db, ingest_enabled=bool(args.allow_ingest), ingest_token=token)
    except LedgerError as exc:
        sys.stderr.write(f"ewp-mcp: {exc}\n")
        return 2
    if args.http:
        host, _, port = args.http.partition(":")
        serve_http(server, host or "127.0.0.1", int(port or "8765"))
        return 0
    serve_stdio(server)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
