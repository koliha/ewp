# Epistemic Warrant Protocol (EWP)

EWP defines the deterministic boundary between what an AI agent’s memory contains and what the agent is epistemically justified in accepting.

Memory is evidence, not truth.

[![EWP](https://img.shields.io/badge/EWP-0.2.0-1e2a32)](#v020)
[![conformance](https://github.com/koliha/ewp/actions/workflows/conformance.yml/badge.svg)](https://github.com/koliha/ewp/actions/workflows/conformance.yml)
[![python](https://img.shields.io/badge/python-3.12%2B-3776ab)](#layout)
[![license](https://img.shields.io/badge/license-MIT-5c6770)](LICENSE)

**EWP-0.2.0.** Policy `reference-v1`. EWP is an epistemic protocol, not an action-authorization framework. Other projects use *warrant* to describe permission to act; EWP uses *epistemic warrant* to describe what an agent is justified in accepting. `may_act()` is deliberately a later gate.

Stores adapt to the protocol. The protocol does not inherit the store’s epistemology.

v0.2.0 tightens scope binding, refuses future-dated checks at T, persists SQLite view completeness, and narrows the serialized `WarrantView` contract. The 26 goldens stay; the evaluator lock moves.

See `NAME.md`, `docs/PROTOCOL_v0.1.md`, `docs/DESIGN_NOTE.md`, `docs/implementer/`, `docs/PLATFORMS.md`, `docs/implementer/LIVE_ADAPTERS.md`, `docs/MCP_CONTRACT.md`, `CONFORMANCE.md`. MCP server: `python3 -m protocol.mcp_server`. The pre-freeze claim/confidence sketch is `historical/docs/MCP_CONTRACT.md` (superseded).

Boundary. Policy. Observations. Permission. Four things. None gets to wear the others' clothes.

```
Memory / Evidence Store
        │
        ▼
   EvidenceView
        │
        ▼
warrant_now(view, policy, evaluated_at)
        │
        ▼
    WarrantView
        │
        ▼
may_act(warrant, action, risk_policy)
        │
        ▼
MAY_ACT | REQUIRE_CONFIRMATION | DENY
```

Stores keep evidence. Warrant is computed. Action is a later gate.

### Quick start

```bash
python3 tests/ci.py
python3 tests/report.py
```

```python
from protocol.types import Policy
from protocol.warrant import warrant_now
from protocol.fixtures import fixture_verified_current, EVAL

view = fixture_verified_current()
result = warrant_now(view, Policy(), EVAL)
print(result.warrant)
```

There is no packaged install yet. The repository itself is currently the reference implementation and conformance suite.

---

## Why this exists

AI agents increasingly keep conversations, observations, documents, tool results, inferred facts, summaries, and prior decisions. Remembering something is not the same as knowing it is true.

A memory store may contain a user’s assertion, an old observation, an LLM-generated summary, a conflicting sensor reading, ten copies of one source, a stale check, and a newer contradictory claim. Most systems are good at storing and retrieving those records.

EWP asks a different question:

> Given the evidence available at time T, under epistemic policy P, what may this agent accept — and why?

It does not assume:

| Common collapse | EWP split |
|---|---|
| stored = true | stored ≠ believed |
| retrieved = important | retrieved ≠ complete |
| repeated = corroborated | repeated ≠ independently sourced |
| summarized = verified | summarized ≠ externally checked |
| current = warranted | store-local “current” ≠ warrant |
| believed = safe to act on | warranted ≠ authorized to act |

That split matters once agents have long-lived memory *and* can take consequential actions.

EWP is not another memory database. It is a deterministic layer above stores and below decision-making.

---

## The model

### 1. Evidence interchange

Stores expose assertions, evidence, provenance, lineage, conflicts, and verification records as an `EvidenceView`.

The store may be SQLite, JSON files, Graphiti, Particles, SurrealDB, or something else. It may keep its own current-fact, invalidation, expiration, ranking, consolidation, deduplication, temporal-edge, and confidence machinery.

Those local projections are inputs. They are not automatically agent beliefs.

### 2. Warrant evaluation

```
warrant_now(evidence_view, policy, evaluated_at) -> WarrantView
```

`warrant_now()` is deterministic. It performs no I/O and no LLM inference. Policy identity is `reference-v1` (rules: `docs/implementer/POLICY.md`).

```
same EvidenceView + same policy version + same evaluated_at
──────────────────────────────────────────────────────────
same WarrantView
```

Warrant is a function, not a stored truth field. Freshness depends on `evaluated_at` on purpose.

### 3. Decision gating

```
may_act(warrant, action, risk_policy)
    -> MAY_ACT | REQUIRE_CONFIRMATION | DENY
```

An agent may be justified in accepting “the customer requested cancellation” and still need confirmation before cancelling a $2M contract. Risk, reversibility, authorization, privacy, money, and safety belong in action policy — not in epistemology.

---

## WarrantView

EWP does not collapse state into one badge (`TRUE`, `VERIFIED`, `DISPUTED`). A proposition can be externally checked and still disputed. It can be accepted and stale. It can have enough evidence and an open conflict.

| Axis | Values |
|---|---|
| acceptance | `UNACCEPTED` / `TENTATIVE` / `ACCEPTED` |
| conflict | `NONE` / `OPEN` / `RESOLVED` |
| verification | `NONE` / `INDIRECT` / `EXTERNAL` / `HUMAN` |
| currency | `CURRENT` / `STALE` / `SUPERSEDED` |
| sufficiency | `SUFFICIENT` / `INSUFFICIENT` / `DEGRADED` |

Example that a single enum cannot hold:

```
acceptance:   TENTATIVE
conflict:     OPEN
verification: EXTERNAL
currency:     CURRENT
sufficiency:  SUFFICIENT
```

---

## Verification is evidence, not a badge

EWP does not persist `verified = true`. A check has method, source, scope, observation time, `result`, and a freshness policy.

```
Proposition:  server01 runs Windows Server 2022
Check:        method tool_observation, result supports,
              observed_at 2026-09-21T18:31Z, scope server01, origin tool
```

`result` is part of the check. `opposes` opens conflict and blocks `ACCEPTED`. `inconclusive` cannot raise `EXTERNAL` or `HUMAN`. Method name alone is never enough: an endogenous origin (`extract`, `turn`, `summary`, …) caps the class at `INDIRECT`, including `human_attestation`.

That check can become stale without ever having been false. Currency is computed at evaluation time from the checks that confer the chosen verification class. A later summary cannot refresh an old tool observation. History is not rewritten.

---

## Source lineage

Ten transformations of one source are not ten independent confirmations.

```
Original article
      ├── summary → agent paraphrase
      └── another summary
```

All share one `lineage_id`. The evaluator counts unique `lineage_id` values on assertions, evidence, and checks — not repetitions.

```
SourceRef {
    source_id, lineage_id, origin_type, origin_locator,
    snapshot_id, content_hash, observed_at,
    extractor_id?, parent_source_id?
}
```

---

## Three confidences that must not be mixed

| Kind | Meaning |
|---|---|
| Assertion confidence | How strongly the source or extractor stated the claim |
| Retrieval score | How relevant a record looks to this query |
| Warrant strength | How strongly policy permits acceptance |

Implementations **MUST NOT** use retrieval relevance, repetition count, memory strength, or assertion confidence as substitutes for warrant.

---

## Core invariants (v0.1.0)

1. Assertions are not beliefs.
2. Beliefs are not truth.
3. Warrant is computed, not persisted as truth.
4. Verification is evidence with method, scope, source, and time — not a proposition badge.
5. Endogenous processing cannot manufacture external verification.
6. Derivation cannot manufacture provenance.
7. Contradiction must survive storage and retrieval.
8. Incomplete retrieval must be visible as `sufficiency=DEGRADED`. Under `reference-v1`, `DEGRADED` also blocks `ACCEPTED`.
9. Epistemic policy and action policy are separate.
10. Semantically equivalent evidence must yield equivalent warrant independent of storage substrate.

Endogenous operations — retrieval, summarization, reflection, dreaming, consolidation, reranking, repetition, graph propagation, LLM critique, multi-agent agreement — may reorganize. They may not turn `verification=NONE` into `verification=EXTERNAL` without new external evidence. Ten agents repeating one hallucinated source are still one lineage.

If P is tentative and P → Q, inference does not make Q externally verified. Epistemic status taints forward.

If the store has A→P and B→¬P but search returns only A, sufficiency is `DEGRADED`. Losing evidence must not raise warrant.

---

## What this repo is

The v0.1.0 *reference kernel*:

- deterministic `warrant_now()` — no network, no LLM, no hidden writes
- shared `protocol/classify.py` used by both reference evaluators
- separate `may_act()`
- 14 canonical fixtures + 12 pathological fixtures + laundering pack
- 26 pinned golden `WarrantView`s
- SQLite and JSON reference adapters
- Graphiti-*shaped* semantic adapter (fake records used by the frozen suite)
- live Graphiti and Mem0 *mappings* (`protocol/graphiti_client_adapter.py`, `protocol/mem0_adapter.py`) — not validated against goldens; live `graphiti-core 0.30.2` is **not** validated
- four-stage runners and field-level diffs

There is no MCP server in this freeze. The tool-contract sketch lives in `historical/docs/MCP_CONTRACT.md`. `docs/MCP_CONTRACT.md` exists only so old links resolve to that sketch. A production `ewp.mcp` server would be an integration façade; it is not required to evaluate warrant. Persona files (`MEMORY.md`) are a generated checkout, not the system of record.

Earlier sketches live in `historical/`. They are not the frozen kernel.

---

## Platforms

### OpenClaw

OpenClaw consumes outbound MCP servers. An EWP MCP server is planned, not shipped in this freeze (`historical/docs/MCP_CONTRACT.md`). When one is running:

```bash
openclaw mcp add ewp --url http://127.0.0.1:8765/mcp
```

| OpenClaw object | Role under EWP |
|---|---|
| Daily notes, transcripts | Raw lineage. Append. Do not rewrite. |
| `USER.md` | Working checkout of preferences. Regenerable. |
| `MEMORY.md` | Persona briefing from `WarrantView`s. Never authoritative. |
| Dreaming / promotion | Candidate generator. Must not raise verification class. |
| Local SQLite machine state | Cache. Not a second ledger. |

Dreaming may rewrite `MEMORY.md`. EWP treats that rewrite as a new assertion, not as verification. Compression must not turn “X is disputed” into “X.”

### Claude, Codex, other MCP clients

Same contract. Prefer HTTP if several clients share one ledger. Prompt rules: fluency is not recollection; `conflict=OPEN` is said out loud; `DEGRADED` means the view is incomplete; store-native write tools stay disconnected.

### Graphiti / Mem0 / Particles / SQLite

Graphiti can be used as a temporal/entity evidence substrate or mirror. Inject `lineage_id` in episode metadata. `invalid_at` is store-local. `valid_at` is not a verification check. Search collapse marks the view `DEGRADED`. Mem0 is an extract-and-retrieve store: default origin is `extract`; retrieval score is not warrant. Particles is a good immutable substrate — agents write only through EWP. SQLite and JSON prove store neutrality.

Full notes: `docs/PLATFORMS.md`. Live client mappings: `docs/implementer/LIVE_ADAPTERS.md`.

Compose EWP with action gates (OpenClaw allowlists, Tenuo, human approval). Do not merge those layers because they share the word *warrant*.

---

## Why EWP sits above the store

| System | Primary concern | EWP adds |
|---|---|---|
| Graphiti / Zep | Temporal knowledge graph and retrieval | Store-independent warrant evaluation |
| Mem0 | Agent memory storage and retrieval | Evidence lineage and deterministic warrant policy |
| OpenClaw native memory | Inspectable agent context and memory | Separation of persona, evidence, and warrant |
| EWP | Epistemic evaluation | Not a general-purpose memory store |

Graphiti adapts to v0.1. v0.1 does not adapt to Graphiti.

---

## Conformance

Schema serialization is not conformance. Behavior is.

```
python3 tests/ci.py
python3 tests/report.py
python3 tests/runner.py
python3 tests/runner_pathological.py
```

CI enforces fixture, evaluator, and golden lock hashes, all 26 goldens, SQLite ≡ JSON, fake-Graphiti isolation, and the laundering pack. Changing a golden or the evaluator requires an explicit version bump, then `python3 tests/ci.py --write-lock`.

Failure classes: `INGEST_LOSS`, `ADAPTER_MAP_LOSS`, `WARRANT_MISMATCH`, `RETRIEVAL_LOSS`, `EXPECTED_DIVERGENCE`.

`EXPECTED_DIVERGENCE` is an observation: the store’s “current fact” may disagree with `warrant_now`. That is the boundary working.

Pathological pack (among others): false supersession, open contradiction, real temporal upgrade, same text / two lineages, three wordings / one lineage, store-current vs verified, weak invalidating strong, maintenance expiry that must not erase a check, retrieval-induced false consensus, extractor polarity flip on one lineage, canonical-without-verification, invalidation cycles.

---

## v0.1.0 freeze

```
Epistemic Warrant Protocol EWP-0.1.0
Policy: reference-v1
Canonical: 14/14
Pathological: 12/12
SQLite PASS
JSON PASS
Fake Graphiti PASS
graphiti-core 0.30.2 — NOT VALIDATED

Fixture set sha256:
910b6e98bee3148460f15303810c8e4c447721252b02c7f4805f3c0ce75b98db
Evaluator set sha256:
cd56535a1d51fc0a6b5a4e1c0cb64636361fcc27f0002a8a352ea62a47bb87b8
Golden set sha256:
95f26b124ac813ef7b6f895bd43c20832f2026bfb8a25513ce6bfd7302088dd3
```

A store that produces a different answer has an adapter or conformance problem, not a license to move the goldens.

---

## Layout

```
protocol/          frozen kernel (classify, warrant, adapters, fixtures)
                   plus live Graphiti/Mem0 mappings (not part of the 26-golden lock)
tests/             conformance, goldens, runners, CI, live-adapter mapping tests
docs/              PROTOCOL, design note, platforms, implementer pack, PDF
                   docs/MCP_CONTRACT.md → pointer to the historical sketch
historical/        pre-freeze warrantmem ledger/MCP/Postgres sketches
                   including historical/docs/MCP_CONTRACT.md
RELEASE.lock.json  fixture + evaluator + golden hashes
pyproject.toml     package metadata (no published install yet)
```

---

## What EWP is not

Not a vector database, knowledge graph, memory engine, truth oracle, LLM fact-checker, or authorization framework.

It does not ask what is ultimately true. That may be inaccessible.

It asks a narrower, computable question: given this bounded evidence view, at this time, under this versioned policy, what may the agent accept — and why?

That answer can be reproduced, tested, inspected, and challenged.

---

## Status

v0.1.0 is frozen. 2026-09-22 pre-freeze pass applies trusted-origin allowlist, DEGRADED-blocks-ACCEPTED, and the evaluator corrections in `CHANGELOG.md`. Architecture work is paused.

New stores may reveal adapter bugs, retrieval loss, missing tests, or a genuine hole. They do not redefine warrant. A case v0.1.0 cannot represent is evidence for v0.2.

Until then: stores keep evidence. Warrant is computed. Action is a later gate.

---

Copyright © 2026 Rob Koliha. MIT License.
