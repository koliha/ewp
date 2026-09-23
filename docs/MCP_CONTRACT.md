# MCP contract — EWP-0.2.0

This is the shipped façade. `python3 -m ewp.mcp_server` speaks the MCP **stdio transport**: newline-delimited JSON-RPC 2.0, one message per line, no header framing. It negotiates MCP protocol revisions `2025-06-18`, `2025-03-26`, and `2024-11-05`.

`--http 127.0.0.1:8765` serves **plain JSON-RPC** at `POST /mcp` for OpenClaw-style clients. It is not MCP Streamable HTTP (no SSE, no session header). Use stdio for standard MCP clients.

The pre-freeze claim/confidence sketch is `historical/docs/MCP_CONTRACT.md`. Do not implement that sketch. Confidence caps, `status=current`, and `claim_verify` raising a scalar are not EWP.

```
agent  →  ewp-mcp  →  EvidenceView store (SQLite: immutable snapshots over an append-only ledger)
                ↘ warrant_now / may_act
```

Agents do not receive store-native write tools.

## Run

```bash
# stdio, read-only for the agent: no writes accepted
python3 -m ewp.mcp_server --db /var/lib/ewp/ledger.sqlite

# stdio, this process is the ingest pipeline
python3 -m ewp.mcp_server --allow-ingest --db /var/lib/ewp/ledger.sqlite

# HTTP: evaluate-only unless the caller presents the ingest token
EWP_INGEST_TOKEN=... python3 -m ewp.mcp_server --http 127.0.0.1:8765 --db /var/lib/ewp/ledger.sqlite
python3 -m ewp.mcp_server --http 127.0.0.1:8765 --ingest-token-file /etc/ewp/ingest.token --db /var/lib/ewp/ledger.sqlite
```

The token is read from `EWP_INGEST_TOKEN` or `--ingest-token-file`, never from argv. `--allow-ingest` is stdio-only: on HTTP it would grant every caller the ingest role, so the server refuses the combination.

A server that can never write (no `--allow-ingest`, no token) opens its ledger **read-only**: `--db` is required, the file must already exist (a mistyped path exits with `ledger not found` instead of creating an empty ledger), and the database handle itself cannot write. Create the ledger with `ewp-ingest` (`QUICKSTART.md`).

OpenClaw:

```bash
EWP_INGEST_TOKEN=... python3 -m ewp.mcp_server --http 127.0.0.1:8765 --db ./ewp.sqlite
openclaw mcp add ewp --url http://127.0.0.1:8765/mcp
```

## Tools

| Tool | Does | Refuses |
|---|---|---|
| `ewp_list_propositions` | Find propositions by id or assertion text; returns ids, latest `view_id`, assertion texts | Discovery only: says what exists, not what is warranted. |
| `ewp_warrant_now` | Stored `proposition_id` (latest snapshot, or `view_id`) or a hypothetical inline `view`, + `evaluated_at` → five axes and the evaluated `view_id` | Missing `evaluated_at`. Unknown proposition or `view_id`. Invalid views. Does not persist the result. |
| `ewp_evidence_view_put` | Store an `EvidenceView` as snapshot `(proposition_id, view_id)`; a missing `view_id` is derived from the content | No ingest role. A `WarrantView` body. Trusted `origin_type` without `ingest_attestation`. A changed record or a changed snapshot under an existing id. |
| `ewp_evidence_view_get` | Load a stored snapshot (latest unless `view_id` is given) | Unknown proposition or `view_id`. |
| `ewp_check_record` | New snapshot = latest + one `VerificationCheck`; returns the new `view_id` (`new_view_id` optional) | No ingest role. Unknown proposition. Trusted origin without attestation. |
| `ewp_evidence_record` | New snapshot = latest + one `EvidenceItem` (optional assertion text); `polarity` is required | No ingest role. Unknown proposition. Missing `polarity`. Trusted origin without attestation. |
| `ewp_may_act` | Action gate over the **stored** view at **server time** | Inline views. A caller-built `WarrantView`. An action without `risk` (`low`/`medium`/`high`) and boolean `reversible`. `evaluated_at` more than 300 s from server time. `risk_policy` from a caller without the ingest role. |
| `ewp_memory_context` | Axes, evidence ids, warnings; `evaluated_at` defaults to server time. When an `EXTERNAL`/`HUMAN` check *opposes* the claim, a warning says so: `verification=EXTERNAL` then means "checked and contradicted", not "confirmed". | A persona biography. `persona` is always `null`. |

`ewp_warrant_now` returns `WarrantView.normative()` (`protocol_version`, identity including the stored `view_id`, time, five axes) plus diagnostics (`rationale_codes`, evidence ids, lineage count). `strength` and `rationale_codes` are not part of the equality contract.

## Snapshots

Every write creates or names an immutable snapshot. Reading `(proposition_id, view_id)` returns exactly what was stored under it, forever. Appends (`ewp_check_record`, `ewp_evidence_record`) atomically create a new snapshot from the latest one, so concurrent appends cannot lose each other. Tools that read take an optional `view_id` and otherwise use the latest snapshot. Re-sending an identical snapshot is a no-op.

## Roles

`SECURITY.md`: EWP does not authenticate evidence entering the ledger. This server *is* the ingest boundary for MCP callers.

**Every write requires the ingest role**, checked before the payload is examined: `--allow-ingest` on stdio, or `Authorization: Bearer <token>` (or `X-EWP-Ingest-Token`) matching the configured token on HTTP. That covers conflicts, lineage edges, and view metadata (`degraded`, `omitted_sources`, `freshness_policy_seconds`, `subjects`), not only records with a trusted origin. Without the role the server is evaluate-only and every write returns `EWP_REFUSE_INGEST_ROLE`.

Writes with a trusted `origin_type` (`tool|document|human|api|vendor|sensor`) additionally need `ingest_attestation=true` on the call. The flag is an explicit declaration by the ingest pipeline. It is not authentication.

The ledger is append-only. Re-sending an identical record is a no-op. Sending an existing assertion, evidence, check, or source id with different content (in any snapshot of the proposition), or changing a snapshot under an existing `view_id`, returns `EWP_REFUSE_IMMUTABLE_RECORD`. A conflict's participants are fixed across snapshots; its `status` and `note` belong to each snapshot, so resolving a conflict is a new snapshot.

## Inline views

An inline `view` is hypothetical: the caller built it, so its provenance is whatever the caller claimed.

- `ewp_warrant_now` evaluates it with every trusted `origin_type` rewritten to `inline:<origin>` (untrusted), and lists them in `inline_origins_demoted`. A caller with the ingest role who also sets `ingest_attestation=true` gets the view evaluated as written.
- `ewp_may_act` refuses inline views (`EWP_REFUSE_INLINE_VIEW_FOR_ACTION`). Action is gated on stored evidence only.

## Time

`ewp_warrant_now` takes any `evaluated_at`: replaying a past T is an audit operation. `ewp_may_act` is a live gate and evaluates at the server clock. A supplied `evaluated_at` must be within 300 s of it.

## Resources

- `ewp://protocol` — protocol identity
- `ewp://proposition/{id}` — latest stored EvidenceView
- `ewp://proposition/{id}/warrant?evaluated_at=` — normative warrant

The two proposition URIs are listed by `resources/templates/list`.

## Packet rules (also the system prompt)

- Memory is evidence, not truth.
- If `conflict=OPEN`, say so. Do not narrate a reconciliation the view does not have.
- If `sufficiency=DEGRADED`, say the view is incomplete.
- Fluency is not recollection. `acceptance≠ACCEPTED` stays visible.
- Do not call Graphiti / Mem0 / Particles write tools from the agent.

## Error codes

| Code | Meaning |
|---|---|
| `EWP_REFUSE_INGEST_ROLE` | A write without the server-side ingest role |
| `EWP_REFUSE_UNATTESTED_TRUSTED_ORIGIN` | Trusted origin without `ingest_attestation=true` |
| `EWP_REFUSE_IMMUTABLE_RECORD` | A stored record id re-sent with different content |
| `EWP_REFUSE_INVALID_EVIDENCE_VIEW` | A value outside a closed enum, a record about another proposition, a conflict that does not name the proposition, or a mistyped field (`subjects` not a list, bad freshness, non-boolean `degraded`) |
| `EWP_REFUSE_INVALID_ARGUMENTS` | A required tool argument is missing or has the wrong type (e.g. `evidence.polarity`) |
| `EWP_REFUSE_PERSIST_WARRANT` | Caller tried to store a WarrantView |
| `EWP_REFUSE_CLIENT_SUPPLIED_WARRANT` | `ewp_may_act` was handed a WarrantView |
| `EWP_REFUSE_INLINE_VIEW_FOR_ACTION` | `ewp_may_act` was handed an inline EvidenceView |
| `EWP_REFUSE_INVALID_ACTION` | Action `risk` not `low`/`medium`/`high`, or `reversible` not a boolean |
| `EWP_REFUSE_EVALUATED_AT_SKEW` | `ewp_may_act` `evaluated_at` too far from server time |
| `EWP_REFUSE_CLIENT_RISK_POLICY` | `risk_policy` from a caller without the ingest role, or a non-boolean flag |
| `EWP_REFUSE_MISSING_CONTENT_HASH` | Incremental record omitted `content_hash` |
| `EWP_REFUSE_MISSING_OBSERVED_AT` | Incremental record omitted `observed_at` |
| `EWP_REFUSE_MISSING_VIEW` | No stored snapshot for that proposition (or that `view_id`) |
| `EWP_REFUSE_MAY_ACT_WITHOUT_ACTION` | `may_act` without an action |
| `EWP_MISSING_EVALUATED_AT` | `ewp_warrant_now` without `evaluated_at` |

Error shapes follow MCP: a failing `tools/call` returns a result with `isError: true` and the code in its text content. A request whose `id` is `null` gets a JSON-RPC `-32600` reply (MCP forbids null ids; a message with no `id` is a notification and is never answered). A failing `resources/read` returns a JSON-RPC error (`-32002` for a missing proposition, `-32602` otherwise) with `data.ewp_code`.

HTTP transport errors: `400` bad `Content-Length` or JSON, `404` unknown path, `413` body over 1 MiB (refused from headers, connection closed), `202` for a notification.

## What this server does not do

- Sign tokens, authenticate users, or authorize tools beyond `may_act`
- Terminate TLS or check origins (bind HTTP to loopback or put it behind a proxy)
- Run an LLM
- Talk to live Graphiti or Mem0 (those adapters are separate; wire them behind this façade if you want)
- Implement the historical claim/confidence MCP
