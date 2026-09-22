# Bake-off — 2026-09-21

Question: is EWP a new database, a policy layer, or a fork?

Against the frozen invariants:

1. Persona is non-authoritative.
2. Only non-introspective verification may raise *epistemic* confidence.
3. Unresolved contradiction is protected from narrative resolution.
4. Compression cannot raise certainty.
5. Retrieval cannot suppress a relevant contradiction without marking the packet degraded.

## Scorecard

| | KIP 2.0 / Anda | Particles | MindGraph | MemoryLACE | YantrikDB | Graphiti |
|---|---|---|---|---|---|---|
| Proposition ≠ belief | **Yes** (normative) | Partial (claim = belief unit; trust is read-time) | Claim/Evidence/Warrant objects | Atomic memory + relations | Memory objects | Fact edges |
| Stored confidence immutable | Assertion payload immutable; new assertion to revise | **Yes** | Confidence on nodes; LLM can assign | Not the focus | Mutable-ish via correct/think | Edges invalidated in place |
| Read-time projection | **Epistemic Projection** | **Effective confidence** (trust × recency) | Retrieve + argue | Reconstruct lifecycle bundle | Ranked recall | Hybrid search |
| Contradiction first-class | Yes in protocol; Brain maintenance may supersede | **INCONSISTENCY + human review** | Contradicts/Refutes edges | Symmetric contradiction links | `conflict` can *resolve* by keeping one side | LLM judge can retire unrelated facts |
| Falsifier / warrant object | Evidence + stance/mode; warrant thinner | Provenance + PSUM; warrant thinner | **First-class Warrant** | Evidence units, not Toulmin warrant | Thin | None |
| Verification ≠ self-grade | Protocol wants instrumentation; Brain still LLM-heavy | Extractor LLM assigns *stored* CONF once; review is human | Discovery vs verification agents in patent; runtime still model-capable | Research retrieval | Agent tools include think/correct | Extraction + contradiction judge |
| Compression cannot raise certainty | Confidence ≠ memory_strength (good). Maintenance can still boost newer assertions in examples. | Stored CONF fixed. EFF can change with policy, not with recall count. | Not guaranteed | Consolidation relations, not confidence inflation | Procedural reinforcement exists | Summaries / sagas |
| Retrieval must attach dissent | Projection can show Alice said / Bob disagrees | Query can flag contestedness at read time | retrieve expands graph | Bundle includes conflicting evidence | Recall may rank one side | Default MCP mixes stale + live |
| MCP today | v1 archived; v2 not the mature plug-in path | `particles mcp serve` (docs: read-only) + Claude Code harvest/inject | mindgraph-mcp 0.20 (MIT) | Paper, not a product MCP | yantrikdb-mcp (MIT + Apache engine) | Official MCP, evolving |
| Persistence | AndaDB / Cognitive Nexus (Rust) | Local append-only store, as-of reads | Hosted + OSS engine | Research | SQLite / cluster | Neo4j / FalkorDB |
| License | MIT (KIP) | Spec CC-BY-4.0; schemas + engine Apache-2.0 | MIT (mcp) | CC BY 4.0 paper | MCP MIT; engine Apache-2.0 | Apache-2.0 |
| Agent-neutral | Protocol first, Brain wraps it | Yes | Company-memory flavored | No | Yes | Yes |

## What each one is actually good for

**KIP 2.0** — steal the *vocabulary and governance split*.
Meaning / Belief / Authority. Proposition exists ≠ is true ≠ Brain accepts. Provenance is not authority. Confidence ≠ memory_strength ≠ salience ≠ SEARCH score. Correction = new Assertion + SUPERSEDING. `$self` reconstructed from evidence.

Do not treat current Brain maintenance as the write gate. Some maintenance examples still mark older facts superseded and boost the newer assertion because the sleeping mind produced the resolution. That is the exact certification we refuse.

MCP story is the weak point: v1 frozen, v2 not a drop-in agent memory server.

**Particles** — steal the *ledger discipline and the agent integration pattern*.
Append-only particles. Stored CONF never mutates. Trust/staleness/contestedness computed at read time. Supersede / retract / dispute in the open. Human `review` compounds into source-trust policy. Claude Code: harvest at session end, bounded digest at session start, agent is stateless compute.

Gaps vs our invariants:
- Extractor LLM writes stored CONF. That is a one-time model grade of the source, which is acceptable if treated as *extractor stance*, not verification.
- No first-class falsification_condition / verification_method / claim_type enum.
- Default MCP path is described as read-only; writes go through deposit/extract/harvest. Fine if harvest = propose.
- Resolution of INCONSISTENCY is designed for *human* ruling. We want the same for agents: model may propose a ruling, only an external check certifies.

**MindGraph** — steal the *Warrant object and layered ontology*.
Claim → Evidence → Warrant → Argument, plus Supports / Refutes / Supersedes / Contradicts. Reality / Epistemic / Intent / Action layers. Bi-temporal company facts. MCP is real.

Risk: more willing to let extraction/verification agents mutate epistemic state. Use as an argument graph behind the ledger, not as the promotion authority.

**MemoryLACE** — steal the *lifecycle retrieval bundle*.
Atomic memories + merge / supersede / contradict; retrieval returns current + historical + supporting + conflicting together. That is rule 5 in research form. Not a product.

**YantrikDB** — useful OpenClaw-shaped *working memory*, not the ledger.
`conflict` that can keep one side is the church door. Use beside OpenClaw checkout, never as SoR.

**Graphiti** — entity/temporal accelerator only. Same as before.

## Recommended assembly (not a greenfield DB)

```
OpenClaw MEMORY.md / Dreaming / daily notes
        │  harvest = PROPOSE only
        ▼
Warrant policy layer  (the only code we should write first)
        │  certify / dispute / degrade-on-pack
        ▼
Particles engine      (immutable claim corpus + as-of + lint/review)
        │  optional episode mirror
        ▼
Graphiti or MindGraph (entities, arguments, valid-time windows)
```

EWP becomes ~2k–4k lines of policy + MCP façade:

- Map Particles particle → our claim view (type, falsifier, verification_method, status).
- Reject any write that raises stored epistemic confidence except `claim_verify`.
- On harvest/Dreaming: `propose` or `propose_reinforcement` only.
- On `memory_context`: if a hit has an open INCONSISTENCY, attach the counterpart or set `packet.degraded=true`.
- On compression: clamp displayed confidence if warrant fields drop.
- Expose the frozen MCP verbs so OpenClaw does not speak Particles or KIP.

If Particles’ stored CONF cannot be extended with warrant fields without a fork, keep warrant in a side table keyed by particle id. Do not fork the engine until a field is truly inexpressible.

## Still-missing product

No current system simultaneously guarantees all five invariants *and* ships them as agent-neutral MCP memory. That gap is real. It is a **policy + contract** gap, not a storage-engine gap.

Build the gate. Import the ledger.
