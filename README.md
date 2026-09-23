# Epistemic Warrant Protocol (EWP)

EWP defines the deterministic boundary between what an AI agent’s memory contains and what the agent is epistemically justified in accepting.

Memory is evidence, not truth.

[![EWP](https://img.shields.io/badge/EWP-0.2.0-1e2a32)](#v020)
[![conformance](https://github.com/koliha/ewp/actions/workflows/conformance.yml/badge.svg)](https://github.com/koliha/ewp/actions/workflows/conformance.yml)
[![python](https://img.shields.io/badge/python-3.12%2B-3776ab)](#layout)
[![license](https://img.shields.io/badge/license-MIT-5c6770)](LICENSE)

**EWP-0.2.0.** Policy `reference-v2`. To try it with Claude and your own data, see [`QUICKSTART.md`](QUICKSTART.md). EWP is an epistemic protocol, not an action-authorization framework. Other projects use *warrant* to describe permission to act; EWP uses *epistemic warrant* to describe what an agent is justified in accepting. `may_act()` is deliberately a later gate.

Stores adapt to the protocol. The protocol does not inherit the store’s epistemology.

v0.2.0 binds verification to declared `subjects[]` as exact ids, scopes supersession to the proposition, treats future, missing, and unparsable times as unavailable at T, refuses values outside the closed enums, refuses views that mix propositions, stores immutable `(proposition, view_id)` snapshots over an append-only ledger, requires adapters to round-trip every field (Graphiti's unavoidable losses are listed), and ships an MCP façade where every write needs a server-side ingest role. Those judgments changed, so the policy is `reference-v2`. `WarrantView` carries `protocol_version`.

See `NAME.md`, `docs/PROTOCOL.md`, `docs/DESIGN_NOTE.md`, `docs/implementer/`, `docs/PLATFORMS.md`, `docs/implementer/LIVE_ADAPTERS.md`, `docs/MCP_CONTRACT.md`, `CONFORMANCE.md`. MCP server: `python3 -m ewp.mcp_server`. The pre-freeze claim/confidence sketch is `historical/docs/MCP_CONTRACT.md` (superseded).

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

To use it with Claude on your own data: [`QUICKSTART.md`](QUICKSTART.md).

```python
from ewp.types import Policy
from ewp.warrant import warrant_now
from ewp.fixtures import fixture_verified_current, EVAL

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

`warrant_now()` is deterministic. It performs no I/O and no LLM inference. Policy identity is `reference-v2` (rules: `docs/implementer/POLICY.md`). It refuses a policy identity it does not implement, and refuses a view with a value outside the closed enums.

```
same protocol version + same EvidenceView + same policy + same evaluated_at
───────────────────────────────────────────────────────────────────────────
same normative WarrantView
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

A check is about something. When a proposition declares `subjects: [server01]`, only a check that also names `server01` can raise `EXTERNAL`. A check on `server02`, on `customer-42`, or one that names no subject at all stays `INDIRECT`.

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

## Core invariants

1. Assertions are not beliefs.
2. Beliefs are not truth.
3. Warrant is computed, not persisted as truth.
4. Verification is evidence with method, scope, source, and time — not a proposition badge.
5. Endogenous processing cannot manufacture external verification.
6. Derivation cannot manufacture provenance.
7. Contradiction must survive storage and retrieval.
8. Incomplete retrieval must be visible as `sufficiency=DEGRADED`. Under `reference-v2`, `DEGRADED` also blocks `ACCEPTED`.
9. Epistemic policy and action policy are separate.
10. Semantically equivalent evidence must yield equivalent warrant independent of storage substrate.

Endogenous operations — retrieval, summarization, reflection, dreaming, consolidation, reranking, repetition, graph propagation, LLM critique, multi-agent agreement — may reorganize. They may not turn `verification=NONE` into `verification=EXTERNAL` without new external evidence. Ten agents repeating one hallucinated source are still one lineage.

If P is tentative and P → Q, inference does not make Q externally verified. Epistemic status taints forward.

If the store has A→P and B→¬P but search returns only A, sufficiency is `DEGRADED`. Losing evidence must not raise warrant.

---

## What this repo is

The v0.2.0 *reference kernel*:

- deterministic `warrant_now()` — no network, no LLM, no hidden writes
- shared `ewp/classify.py` used by both reference evaluators
- separate `may_act()`
- 14 canonical + 12 pathological + 25 hardening fixtures (laundering, subject binding, time at T, supersession scope, zero freshness), plus 23 invalid views that must be refused
- 26 pinned golden `WarrantView`s; all 51 fixtures' expected axes pinned in `docs/implementer/`
- an independent third evaluator (`docs/implementer/third_eval.py`) written from the policy text alone
- SQLite and JSON reference adapters (immutable snapshots; SQLite over an append-only ledger)
- `ewp-ingest` to load your own evidence from JSON, and `ewp-mcp` to serve it read-only to Claude (`QUICKSTART.md`)
- Graphiti-*shaped* semantic adapter (fake records)
- live Mem0 mapping and an **experimental** live Graphiti mapping (`ewp/mem0_adapter.py`, `ewp/graphiti_client_adapter.py`); every fixture round-trips through Mem0 with every field intact and through fake Graphiti with only its listed losses; live `graphiti-core 0.30.2` is **not** validated
- MCP façade (`ewp/mcp_server.py`, `tests/test_mcp.py`): MCP stdio transport or plain JSON-RPC `POST /mcp`; contract in `docs/MCP_CONTRACT.md`
- four-stage runners and field-level diffs

Warrant evaluation does not require MCP. Persona files (`MEMORY.md`) are a generated checkout, not the system of record.

The pre-freeze claim/confidence sketch is `historical/docs/MCP_CONTRACT.md` (superseded). Earlier warrantmem sketches live in `historical/`. They are not the kernel.

---

## Platforms

### OpenClaw

OpenClaw consumes outbound MCP servers. Run the shipped façade and add it:

```bash
EWP_INGEST_TOKEN=... python3 -m ewp.mcp_server --http 127.0.0.1:8765 --db ./ewp.sqlite
openclaw mcp add ewp --url http://127.0.0.1:8765/mcp
```

Contract: `docs/MCP_CONTRACT.md`. Stdio is the standard MCP transport (newline-delimited JSON-RPC). HTTP is plain JSON-RPC, not MCP Streamable HTTP. Every write needs the server-side ingest role (`--allow-ingest` on stdio, the token on HTTP); without it the server is evaluate-only. Give the token to the ingest pipeline, not the agent. `ewp_may_act` gates only stored evidence, at server time.

| OpenClaw object | Role under EWP |
|---|---|
| Daily notes, transcripts | Raw lineage. Append. Do not rewrite. |
| `USER.md` | Working checkout of preferences. Regenerable. |
| `MEMORY.md` | Persona briefing from `WarrantView`s. Never authoritative. |
| Dreaming / promotion | Candidate generator. Must not raise verification class. |
| Local SQLite machine state | Cache. Not a second ledger. |

Dreaming may rewrite `MEMORY.md`. EWP treats that rewrite as a new assertion, not as verification. Compression must not turn “X is disputed” into “X.”

### Claude, Codex, other MCP clients

Same contract over stdio: `python3 -m ewp.mcp_server --db ./ewp.sqlite`. Point several clients at the same `--db` to share one ledger. Prompt rules: fluency is not recollection; `conflict=OPEN` is said out loud; `DEGRADED` means the view is incomplete; store-native write tools stay disconnected.

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

Graphiti adapts to the protocol. The protocol does not adapt to Graphiti.

---

## Conformance

Schema serialization is not conformance. Behavior is.

```
python3 tests/ci.py
python3 tests/report.py
python3 tests/runner.py
python3 tests/runner_pathological.py
```

CI enforces the fixture, evaluator, policy, golden, and implementer-pack lock hashes; all 26 goldens; all 51 fixtures through the codec, SQLite, JSON, Mem0, and fake Graphiti with identical axes and fields; 23 invalid views refused by all three evaluators; fake-Graphiti isolation; the hardening pack; live-adapter mappings; the MCP façade; and the third evaluator. Changing a golden, the pack, the policy text, or the evaluator requires an explicit version change, then `python3 tests/ci.py --write-lock`. `tests/report.py` only says `CONFORMANT` for a CI stamp taken on the exact CI surface it is run on (kernel, adapters, MCP server, tests, implementer pack, examples, workflow).

Failure classes: `INGEST_LOSS`, `ADAPTER_MAP_LOSS`, `WARRANT_MISMATCH`, `RETRIEVAL_LOSS`, `EXPECTED_DIVERGENCE`.

`EXPECTED_DIVERGENCE` is an observation: the store’s “current fact” may disagree with `warrant_now`. That is the boundary working.

Pathological pack (among others): false supersession, open contradiction, real temporal upgrade, same text / two lineages, three wordings / one lineage, store-current vs verified, weak invalidating strong, maintenance expiry that must not erase a check, retrieval-induced false consensus, extractor polarity flip on one lineage, canonical-without-verification, invalidation cycles.

---

## v0.2.0 lock

<a id="v020"></a>

```
Epistemic Warrant Protocol EWP-0.2.0
Policy: reference-v2
Canonical: 14/14
Pathological: 12/12
Hardening: 25/25
Invalid refused: 23/23
SQLite PASS
JSON PASS
Fake Graphiti PASS
Mem0 (fake client) PASS
graphiti-core 0.30.2 — NOT VALIDATED

fixture_set_sha256:
b87f3c5f6f4032c390cf31067d5c425685cd0f9eec990f6ea7a3848e3fb7bfb9
evaluator_set_sha256:
fc7085c7014d13139f2d39635bc46a0e29334c5b4e2bf743c1a4450064ebaf0b
policy_set_sha256:
8056fb34a42546166a21554a16af87cb78127540e1c0616dd7d9f681b56dc66a
golden_set_sha256:
1db7cab34639a87ce35c36635d4b6cffa46ba08855107fc9a04a4b89348a81c8
implementer_pack_sha256:
2abab1f3d426166d1cea8eed052def4fb7d5cc4262e1dd11e57c3817f061f2df
```

A store that produces a different answer has an adapter or conformance problem, not a license to move the goldens.

---

## Layout

```
ewp/               kernel (classify, warrant, adapters, fixtures, MCP server)
                   plus live Graphiti/Mem0 mappings
tests/             conformance, goldens, adapter round trips, runners, CI,
                   live-adapter and MCP tests
docs/              PROTOCOL.md, design note, platforms, implementer pack, PDFs
                   docs/MCP_CONTRACT.md — shipped MCP façade
historical/        pre-freeze warrantmem ledger/MCP/Postgres sketches
                   including historical/docs/MCP_CONTRACT.md (superseded)
RELEASE.lock.json  fixture + evaluator + policy + golden + implementer-pack hashes
pyproject.toml     package metadata (no published install yet; ewp-mcp entry point)
```

---

## What EWP is not

Not a vector database, knowledge graph, memory engine, truth oracle, LLM fact-checker, or authorization framework.

It does not ask what is ultimately true. That may be inaccessible.

It asks a narrower, computable question: given this bounded evidence view, at this time, under this versioned policy, what may the agent accept — and why?

That answer can be reproduced, tested, inspected, and challenged.

---

## Status

EWP-0.2.0 under policy `reference-v2` is not yet released and is still changing in review. The 26 golden axes are unchanged from 0.1.0; their identity fields now read `reference-v2` and `EWP-0.2.0`. The hardening pack (25) and the invalid pack (23) are locked. Known limits: conflict rows and lineage edges carry no timestamp, so they are not filtered by availability at T; assertions carry no polarity. See `CHANGELOG.md`.

New stores may reveal adapter bugs, retrieval loss, missing tests, or a genuine hole. They do not redefine warrant.

Stores keep evidence. Warrant is computed. Action is a later gate.

---

Copyright © 2026 Rob Koliha. MIT License.
