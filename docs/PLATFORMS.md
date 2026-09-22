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
# planned process (not shipped in v0.1.0 — see historical/docs/MCP_CONTRACT.md)
python3 -m ewp.mcp --http 127.0.0.1:8765

openclaw mcp add ewp --url http://127.0.0.1:8765/mcp
```

Keep OpenClaw’s own files as *inputs and working memory*, not as the system of record:

| OpenClaw object | Role under EWP |
|---|---|
| Daily notes, session transcripts | Raw lineage events. Append. Do not rewrite. |
| `USER.md` | Working checkout of preferences. Regenerable. |
| `MEMORY.md` | Persona briefing. Generated from `WarrantView`s. Never authoritative. |
| Dreaming / memory-core promotion | Candidate generator only. Promotion does not raise verification class. |
| SQLite-backed machine state | Fine as local cache. Not a second ledger. |

Suggested OpenClaw loop:

1. Session starts. Call `memory_context` with the user’s question and `lineage_id`.
2. Agent works. Tool results become evidence via `evidence_record` / `check_record`.
3. Agent may say “I remember.” EWP packet must still show inherited-from / verified / disputed.
4. Session ends. Transcript is an event. Dreaming may propose a persona rewrite. EWP accepts the rewrite only as a new assertion, not as a verification.

Do not let Dreaming rebase `X is disputed` into `X`. Compression monotonicity is the whole point of putting EWP in front.

## Claude, Codex, and other MCP clients

Same MCP surface. Add the server once. Prefer HTTP in multi-agent setups so several clients share one ledger.

Rules that belong in the client system prompt, not in the store:

- Do not treat first-person fluency as recollection.
- If the packet says `conflict=OPEN`, say so. Do not narrate a reconciliation the ledger does not have.
- If `sufficiency=DEGRADED`, say the view is incomplete.
- Do not call store-native write tools.

## Graphiti / Zep

Use Graphiti as a temporal/entity mirror, not as warrant.

- Ingest episodes with `episode_metadata.lineage_id` set by EWP.
- Adapter maps edges → `EvidenceView`. `invalid_at` is store-local. `valid_at` is not a verification check.
- Search collapse must mark the view `DEGRADED`.
- Live pin: `graphiti-core 0.30.2`. Graphiti adapts to EWP. EWP does not adapt to Graphiti.

## Particles

Particles is a good immutable claim substrate. Expose Particles MCP **read-only** to operators if needed. Agents write only through EWP (`claim_propose`, `check_record`, `dispute_open`). Otherwise Particles’ `particle_assert` bypasses policy.

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
