# MCP contract — EWP v0.1

Transport: streamable HTTP (`/mcp`) and stdio.
All mutating tools append events. None rewrite lineage.

Agent-facing rule: you may *narrate* the graph. You may not *rewrite* the graph into a biography.

## Tools

### memory_context

Produce a bounded working packet with three channels.

```
query: string
lineage_id: string
branch_id?: string
token_budget?: number          # default 2000
include_disputed?: boolean     # default true
as_of?: string                 # ISO timestamp for point-in-time
```

Returns:

```
persona: string                # disposable briefing
claims: ClaimView[]            # scored, warrant attached
disputes: DisputeView[]
provenance: { claim_id, originating_node, parent_claim_ids, events[] }
warnings: string[]             # e.g. "compression dropped falsifier on claim X; confidence reduced"
```

### claim_propose

Append a proposition. Status starts at `proposed`. Confidence capped by claim_type:

| type | max confidence without external check |
| --- | --- |
| model_introspection / inference with no evidence | 0.40 |
| convention | 0.50 |
| report | 0.55 |
| observation with tool_result event | 0.75 |
| external_check | 0.90 |

```
proposition, scope?, claim_type, evidence_event_ids[],
falsification_condition?, confidence_basis, parent_claim_ids[],
valid_from?, valid_until?, expiry_policy?
```

Cannot set `status=current` in this call.

### claim_verify

Attach an external check. **Only this tool may raise confidence**, and only when `verification_method != model_introspection`.

```
claim_id
method: external_clock | tool_observation | human_attestation | independent_reproduction | document_quote
event_payload: object          # stored as event_kind=external_check
new_confidence?: number        # must be justified by method; server may clamp
```

### claim_dispute

Preserve a live contradiction. Sets both claims to `disputed` (or keeps `current` on neither until resolved).

```
claim_id_a
claim_id_b
note?
```

Does not invent “I used to believe A.” That sequence is only representable if a supersession chain exists.

### claim_supersede

Replace without erasing history. Old claim → `superseded`. New claim starts `proposed` unless a verification event is attached in the same call.

```
old_claim_id
proposition
reason
verification?: { method, event_payload }
```

### claim_retract

```
claim_id
reason
```

Status → `retracted`. Confidence may only fall.

### claim_explain

Walk provenance and warrant.

```
claim_id
depth?: number
```

Returns the claim, parent claims, evidence events, mutations (with confidence_before/after), open contradictions, checksum.

### lineage_branch / lineage_merge

```
lineage_branch(from_node_id, new_branch_id, note?)
lineage_merge(from_branch_ids[], into_branch_id, strategy: 'keep_disputes' | 'require_resolution')
```

`keep_disputes` is the default. `require_resolution` fails if open contradictions exist.

### session_open / session_close

```
session_open(lineage_id, branch_id?, agent_label?, model_label?, parent_node_ids?)
  → node_id

session_close(node_id, proposed_claims?: ClaimDraft[])
```

Closing extracts *proposals* only. The closing model cannot verify, supersede-as-current, or rewrite events. Dreaming / compaction hooks must use this path.

### clock_check

First-class because the originating artifact demanded it.

```
claimed_now?: string
```

Compares model-claimed time to host UTC. Writes an `external_check` event. If they diverge, auto-proposes or verifies the procedure claim “do not trust model-supplied temporal context.”

## Resources (read-only)

- `ewp://lineage/{id}/claims?status=current,disputed`
- `ewp://claim/{id}`
- `ewp://node/{id}/events`
- `ewp://persona/{lineage_id}?branch=`

## Server-side refusals

Reject:

- `claim_propose` with `confidence > cap(type, method)`
- any mutation that raises confidence except `claim_verify` with a non-introspective method
- `claim_supersede` that deletes the old row
- persona snapshot written into `claims` as `observation`
- compression jobs that omit `falsification_condition` while keeping the same confidence
