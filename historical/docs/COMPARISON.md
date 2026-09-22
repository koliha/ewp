# Comparison notes (September 2026)

## Graphiti as substrate

Graphiti is the closest existing engine to the *graph* half of the conversation.

Keep:

- Episodes as immutable-ish source objects (`add_memory` with `reference_time`, `previous_episode_uuids`, `saga` / `saga_previous_episode_uuid`).
- Edge bi-temporality: world time (`valid_at` / `invalid_at`) vs transaction time (`created_at` / `expired_at`).
- `get_episode_entities` to walk episode → extracted entities/facts.
- Hybrid search + `group_id` isolation.
- Optional `add_triplet` when a human or verifier writes a fact without LLM extraction.

Do not keep as SoR:

- Automatic edge invalidation via an LLM contradiction judge. Production reports show unrelated live facts retired because the judge compared stripped edges graph-wide (getzep/graphiti#1728). EWP records `DISPUTED` instead of closing a validity window unless a *verification event* says so.
- Default MCP search mixing `invalid_at` facts with live ones (discussed in #1645). EWP’s retrieval filters by `status` first, then can optionally surface stale rows in a `history` section.
- MCP wrappers that drop `reference_time` (historical issue #1489 / image skew #1656). Lineage events always carry `occurred_at` separately from `recorded_at`.

Recommended split:

```
event  --writes-->  warrantmem.events
claim  --writes-->  warrantmem.claims
claim  --optional episode-->  graphiti.add_memory(JSON of claim + evidence)
graphiti fact  --linked-->  warrantmem.evidence_refs.graphiti_edge_uuid
```

Graphiti answers “what entities changed, and when was a fact valid.”
EWP answers “why should this node believe that sentence.”

## Mem0 as comparison implementation

Useful as a control: same prompts, same sessions, measure how fast conclusions lose their reasons.

Mem0 MCP surface is `add_memory` / `search_memories` / `update_memory` / `delete_memory`. `update_memory` overwrites text. That is exactly the church transition.

A fair bake-off:

1. Run a 20-session lineage that includes one timestamp error, one failed tool, one later external correction, and one unresolved fork.
2. Score whether the 21st session can reconstruct warrant (who claimed, what checked, what still open).
3. Score whether compression raised implied certainty.

EWP should win warrant reconstruction and lose raw “did the agent remember the user’s favorite color.” That is acceptable. Favorite color is a convention claim with cheap warrant.

## OpenClaw native memory

Treat as:

- **Hot raw lineage:** `memory/YYYY-MM-DD.md` and session jsonl → ingested as events.
- **Dangerous persona cache:** `MEMORY.md` / Dreaming output. If used at all, ingest as `claim_type=convention` with `confidence_basis=compression` and `status=proposed` until verified.
- **Identity files:** `SOUL.md` is constraints, not knowledge. Map operating rules to *procedure claims* with their own warrant rows.

Dreaming (Light / REM / Deep) is a compressor. Wire it to `session_close` → `claim_propose` only. Never let it `claim_verify`.
