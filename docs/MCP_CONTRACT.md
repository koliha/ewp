# MCP contract — EWP-0.2.0

This is the shipped façade. `python3 -m protocol.mcp_server` speaks **Content-Length framed** JSON-RPC 2.0 on stdio (MCP). `--http 127.0.0.1:8765` serves plain JSON-RPC `POST /mcp` for OpenClaw-style clients. HTTP is not framed MCP and is not an authenticated production write API unless `--ingest-token` is set.

The pre-freeze claim/confidence sketch is `historical/docs/MCP_CONTRACT.md`. Do not implement that sketch. Confidence caps, `status=current`, and `claim_verify` raising a scalar are not EWP.

```
agent  →  ewp-mcp  →  EvidenceView store (SQLite default)
                ↘ warrant_now / may_act
```

Agents do not receive store-native write tools.

## Run

```bash
python3 -m protocol.mcp_server --stdio --allow-ingest --db /var/lib/ewp/ledger.sqlite
python3 -m protocol.mcp_server --http 127.0.0.1:8765 --ingest-token "$EWP_INGEST_TOKEN" --db /var/lib/ewp/ledger.sqlite
```

OpenClaw:

```bash
python3 -m protocol.mcp_server --http 127.0.0.1:8765 --ingest-token "$EWP_INGEST_TOKEN" --db ./ewp.sqlite
openclaw mcp add ewp --url http://127.0.0.1:8765/mcp
```

## Tools

| Tool | Does | Refuses |
|---|---|---|
| `ewp_warrant_now` | `view` or stored `proposition_id` + `evaluated_at` → five axes | Missing `evaluated_at`. Does not persist the result. |
| `ewp_evidence_view_put` | Store an `EvidenceView` | A `WarrantView` body. Trusted `origin_type` without a server-side ingest role. |
| `ewp_evidence_view_get` | Load a stored view | — |
| `ewp_check_record` | Append a `VerificationCheck` | Trusted origin without attestation |
| `ewp_evidence_record` | Append an `EvidenceItem` (optional assertion text) | Trusted origin without attestation |
| `ewp_may_act` | Action gate. Requires an `action` and evaluates the stored/inline view | A caller-built `WarrantView`. Inferring permission from axes alone. |
| `ewp_memory_context` | Axes, evidence ids, warnings | A persona biography. `persona` is always `null`. |

`ewp_warrant_now` returns `WarrantView.normative()` plus diagnostic ids. `strength` is not in the interchange object.

## Ingest role

`SECURITY.md`: EWP does not authenticate evidence entering the ledger. This server *is* the ingest boundary for MCP callers. The client boolean `ingest_attestation` is not authentication.

Trusted writes (`origin_type` in `tool|document|human|api|vendor|sensor`) require:

1. A server-side ingest role — `--allow-ingest` on stdio, or `Authorization: Bearer` matching `--ingest-token` on HTTP.
2. `ingest_attestation=true` on the tool call.

Without the role the tool returns `EWP_REFUSE_INGEST_ROLE`. With the role but without the flag it returns `EWP_REFUSE_UNATTESTED_TRUSTED_ORIGIN`. HTTP without a token is evaluate-only.

## Resources

- `ewp://protocol` — protocol identity
- `ewp://proposition/{id}` — stored EvidenceView
- `ewp://proposition/{id}/warrant?evaluated_at=` — normative warrant

## Packet rules (also the system prompt)

- Memory is evidence, not truth.
- If `conflict=OPEN`, say so. Do not narrate a reconciliation the view does not have.
- If `sufficiency=DEGRADED`, say the view is incomplete.
- Fluency is not recollection. `acceptance≠ACCEPTED` stays visible.
- Do not call Graphiti / Mem0 / Particles write tools from the agent.

## Error codes

| Code | Meaning |
|---|---|
| `EWP_REFUSE_PERSIST_WARRANT` | Caller tried to store a WarrantView |
| `EWP_REFUSE_UNATTESTED_TRUSTED_ORIGIN` | Trusted origin without ingest attestation flag |
| `EWP_REFUSE_INGEST_ROLE` | Trusted origin write without server-side ingest role |
| `EWP_REFUSE_CLIENT_SUPPLIED_WARRANT` | `ewp_may_act` was handed a WarrantView |
| `EWP_REFUSE_MISSING_CONTENT_HASH` | Incremental record omitted `content_hash` |
| `EWP_REFUSE_MISSING_OBSERVED_AT` | Incremental record omitted `observed_at` |
| `EWP_REFUSE_MISSING_VIEW` | No stored view for that proposition |
| `EWP_REFUSE_MAY_ACT_WITHOUT_ACTION` | `may_act` without an action |
| `EWP_MISSING_EVALUATED_AT` | Time was omitted |

## What this server does not do

- Sign tokens, authenticate users, or authorize tools beyond `may_act`
- Run an LLM
- Talk to live Graphiti or Mem0 (those adapters are separate; wire them behind this façade if you want)
- Implement the historical claim/confidence MCP
