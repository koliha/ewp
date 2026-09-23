# Using EWP with platforms

EWP is the policy façade. Platforms keep doing what they are good at. They do not become the authority on what the agent may accept.

```
OpenClaw / Claude / Codex / other MCP agents
                    │
                    ▼
              EWP MCP
       policy + retrieval + warrant_now
                    │
          +---------+---------+
          │                   │
          v                   v
   evidence store        optional mirrors
   SQLite / Particles    Graphiti / MindGraph
```

Agents never get store mutation tools directly. If someone wires an agent straight to Particles or Graphiti, they have bypassed EWP on purpose.

## OpenClaw

OpenClaw already consumes outbound MCP servers. That is the integration.

```bash
EWP_INGEST_TOKEN=... python3 -m ewp.mcp_server --http 127.0.0.1:8765 --db ./ewp.sqlite
openclaw mcp add ewp --url http://127.0.0.1:8765/mcp
```

The HTTP endpoint is plain JSON-RPC, not MCP Streamable HTTP. Without the ingest token it is evaluate-only. Give the token to the ingest pipeline, not to the agent.

Contract: `docs/MCP_CONTRACT.md`. Pre-freeze sketch: `historical/docs/MCP_CONTRACT.md` (superseded).

Keep OpenClaw’s own files as *inputs and working memory*, not as the system of record:

| OpenClaw object | Role under EWP |
|---|---|
| Daily notes, session transcripts | Raw lineage events. Append. Do not rewrite. |
| `USER.md` | Working checkout of preferences. Regenerable. |
| `MEMORY.md` | Persona briefing. Generated from `WarrantView`s. Never authoritative. |
| Dreaming / memory-core promotion | Candidate generator only. Promotion does not raise verification class. |
| SQLite-backed machine state | Fine as local cache. Not a second ledger. |

Suggested OpenClaw loop:

1. Session starts. Call `ewp_memory_context` with the proposition and `evaluated_at`.
2. Agent works. The harness or tool runner — which holds the ingest token, the agent does not — records tool results as evidence via `ewp_evidence_record` / `ewp_check_record`.
3. Agent may say “I remember.” EWP packet must still show inherited-from / verified / disputed.
4. Session ends. Transcript is an event. Dreaming may propose a persona rewrite. EWP accepts the rewrite only as a new assertion, not as a verification.

Do not let Dreaming rebase `X is disputed` into `X`. Compression monotonicity is the whole point of putting EWP in front.

## Claude, Codex, and other MCP clients

Same MCP surface over the standard stdio transport. Each client launches its own `ewp-mcp --db <path>` (`python3 -m ewp.mcp_server`); point them at the same `--db` file to share one ledger. The ledger must already exist. The agent-facing process runs without `--allow-ingest`, so the agent can evaluate but not write. Load evidence with `ewp-ingest` (see `QUICKSTART.md`) or a separate `--allow-ingest` process.

Rules that belong in the client system prompt, not in the store:

- Do not treat first-person fluency as recollection.
- If the packet says `conflict=OPEN`, say so. Do not narrate a reconciliation the ledger does not have.
- If `sufficiency=DEGRADED`, say the view is incomplete.
- Do not call store-native write tools.

## Graphiti / Zep

Use Graphiti as a temporal/entity mirror, not as warrant.

- Ingest episodes with `episode_metadata.lineage_id` set by EWP.
- The locked suite uses fake Graphiti-shaped records (`ewp/graphiti_adapter.py`). Every fixture must round-trip through it with identical axes.
- Park the view's and each check's `subjects[]` with the checks. Dropping them changes warrant.
- The live client mapping is `ewp/graphiti_client_adapter.py` — see `docs/implementer/LIVE_ADAPTERS.md`.
- Adapter maps edges → `EvidenceView`. `invalid_at` is store-local. `valid_at` is not a verification check.
- Search collapse must mark the view `DEGRADED`.
- Live pin: `graphiti-core 0.30.2`. Live `graphiti-core` is **not** validated. Graphiti adapts to EWP. EWP does not adapt to Graphiti.

## Mem0

Use Mem0 as an extract-and-retrieve store, not as warrant.

- Default `origin_type` is `extract` (endogenous). That cannot raise `EXTERNAL` / `HUMAN`.
- Put `lineage_id` and a trusted `origin_type` in `metadata.ewp` at write time, or ten extracts of one transcript look independent.
- Write assertions and evidence as separate memories with their own polarity and timestamps (`Mem0Adapter.ingest_view` does). Mem0's `created_at` is ingest time, not observation time.
- Retrieval `score` is adapter metadata, never warrant strength.
- `search` that drops memories the store still holds must mark the view `DEGRADED`.
- Live mapping: `ewp/mem0_adapter.py`. Notes: `docs/implementer/LIVE_ADAPTERS.md`.

## Particles

Particles is a good immutable claim substrate. Expose Particles MCP **read-only** to operators if needed. Writes go only through EWP's ingest role (`ewp_evidence_view_put`, `ewp_evidence_record`, `ewp_check_record`). Otherwise Particles’ `particle_assert` bypasses policy.

## SQLite and JSON

Reference adapters. Use them in tests and in small deployments. They exist to prove store neutrality, not to win a database bake-off.

## Action gates stay outside EWP

OpenClaw tool policy, Tenuo warrants, human-approval MCP — those answer *may the agent do this*. EWP answers *may the agent accept this*. Compose them:

```
warrant_now(...) → WarrantView
may_act(warrant, action, risk_policy) → MAY_ACT | REQUIRE_CONFIRMATION | DENY
platform authorization (Tenuo / OpenClaw allowlist / human gate)
```

Do not fold those layers together because they share the English word *warrant*.
