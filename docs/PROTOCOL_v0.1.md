# Epistemic Warrant Protocol (EWP) v0.2 — 2026-09-22

Status: current conceptual contract. Policy identity remains `reference-v1` with the v0.2 tightenings below. The 26 frozen goldens are unchanged; evaluator and adapter contracts are not.

Filename kept as `PROTOCOL_v0.1.md` so existing links resolve. The text below is the EWP-0.2.0 conceptual contract.


The core object is not memory, truth, or confidence. It is a reproducible answer to:

> Given this bounded evidence view, at this time, under this versioned epistemic policy, what may the agent accept — and what evidence warrants that acceptance?

Everything upstream is evidence preservation.
Everything downstream is decision policy.

## Architecture

```
Evidence stores (Particles / Graphiti / SurrealDB / SQLite / …)
        │
        │  Evidence Interchange
        ▼
   EvidenceView  (immutable snapshot, view_id)
        │
        │  warrant_now(view, policy, evaluated_at)
        ▼
   WarrantView
        │
        │  may_act(warrant, action, risk_policy)
        ▼
   MAY_ACT | REQUIRE_CONFIRMATION | DENY
```

Agents speak only to the policy façade. Store mutation tools are not exposed to agents.

## Function signatures

```
warrant_now(evidence_view, policy, evaluated_at) -> WarrantView
may_act(warrant_view, action, risk_policy) -> ActDecision
```

Reproducibility MUST:

```
same evidence_view + same policy.version + same evaluated_at
  => same WarrantView
```

`evidence_view` is a stable snapshot or carries an immutable `view_id`.
Freshness is a function of `evaluated_at`. Do not hide time inside the store.

## Evidence interchange (stores MUST expose)

```
get_assertions(proposition_id | query) -> Assertion[]
get_evidence(proposition_id) -> Evidence[]
get_lineage(proposition_id | source_id) -> LineageEdge[]
get_conflicts(proposition_id) -> Conflict[]
get_checks(proposition_id) -> VerificationCheck[]
```

Stores MUST NOT present a local projection as universal belief.

## Required types

### SourceRef

```
SourceRef {
  source_id          # this evidentiary object
  lineage_id         # common ancestor of derived copies
  origin_type        # document | turn | tool | human | extract | …
  origin_locator     # URL, path, episode id, tool call id
  snapshot_id
  content_hash
  observed_at
  extractor_id?
  parent_source_id?
}
```

`lineage_id` answers: are these allegedly independent observations descendants of one source?

### VerificationCheck

```
VerificationCheck {
  check_id
  method             # tool_observation | external_clock | document_quote | human_attestation | independent_reproduction
  scope              # what was actually inspected
  source             # SourceRef
  observed_at
  result             # supports | opposes | inconclusive
}
```

Verification is evidence with method, scope, source, time, and `result`. It is not a badge on a proposition.

`result` is normative:

- `supports` — the check bears on P in the supporting direction
- `opposes` — the check bears on P against it; this opens `conflict=OPEN` and blocks `ACCEPTED`
- `inconclusive` — a check ran; it cannot raise verification class to `EXTERNAL` or `HUMAN`

Method name is not enough. Only origins `tool`, `document`, `human`, `api`, `vendor`, `sensor` may raise `HUMAN` or `EXTERNAL`. If `source.origin_type` is endogenous or unknown (`extract`, `turn`, `derived`, `summary`, `model_introspection`), a human or external method is capped at `INDIRECT`.

### WarrantView

Axes are independent. They MUST NOT be collapsed into one exclusive enum.

The block below is a **conceptual view** of the axes plus diagnostics. The normative serialization is the flatter object in `docs/implementer/SCHEMA.md` and `WarrantView.normative()`: identity, time, five axes, rationale_codes. Diagnostic arrays on the Python `WarrantView` are reference-implementation convenience.

```
WarrantView {
  proposition_id
  assertions[]
  supporting_evidence[]
  opposing_evidence[]
  warrant {
    acceptance     UNACCEPTED | TENTATIVE | ACCEPTED
    conflict       NONE | OPEN | RESOLVED
    verification   NONE | INDIRECT | EXTERNAL | HUMAN
    currency       CURRENT | STALE | SUPERSEDED
    sufficiency    SUFFICIENT | INSUFFICIENT | DEGRADED
    strength       # policy-computed; not assertion confidence
    rationale_codes[]
  }
  verification {
    checks[]
    freshest_check
    freshness_policy
    stale
  }
  conflicts { open[], resolved[] }
  completeness { retrieval_scope, degraded, omitted_sources[] }
  lineage { derived_from[], supersedes[], superseded_by[] }
  falsification { conditions[] }
  evaluated_at
  policy_id
  policy_version
  view_id
}
```

`warrant.*` is computed. It is not persisted as epistemic truth.

## Policy identity

```
Policy.policy_id  = reference-v1
Policy.version    = reference-v1
```

`WarrantView.policy_id` and `WarrantView.policy_version` MUST echo those strings. Do not emit `epistemic-v0.1` / `0.1.0`.

## Conflict

`conflict=OPEN` when any of:

- a `Conflict` row has `status=open`
- evidence contains both `supports` and `opposes`
- checks contain both `result=supports` and `result=opposes`

A missing `Conflict` row must not hide opposition already present in the view.

## Currency

- lineage edge `superseded_by` → `SUPERSEDED`
- a check with `observed_at` after `evaluated_at` is not available at T and cannot confer class, refresh currency, or open conflict
- else the newest check that confers the chosen verification class is older than `freshness_policy_seconds` at `evaluated_at` → `STALE`
- else `CURRENT`

A later endogenous check cannot refresh `EXTERNAL` or `HUMAN` currency.

## Scope and subjects

`VerificationCheck.scope` is opaque text. v0.2 also allows optional `subjects[]` on the check and on the view as a store-neutral identity primitive. Binding rule: if check and view name the same identifier family (`customer`, `server`, `contract`, …) and the tokens differ, the check cannot raise `HUMAN` or `EXTERNAL`. Adapters SHOULD populate `subjects` when the store has a real subject key; the evaluator still extracts identifier-shaped tokens from `scope` and view text when `subjects` is empty.

## Three confidences (MUST NOT be substituted)

| Name | Meaning |
|---|---|
| assertion confidence | how strongly the asserting process/source expressed the claim |
| retrieval score | how relevant a record appears to the current query |
| warrant strength | how strongly policy permits acceptance |

Implementations MUST NOT use retrieval relevance, repetition count, memory strength, or assertion confidence as substitutes for warrant.

## Constitutional rules

1. Assertions are not beliefs.
2. Beliefs are not truth.
3. Warrant is computed, not persisted as truth.
4. Verification is evidence with method, scope, source, and time — not a proposition badge.
5. Endogenous processing cannot manufacture external verification.
6. Derivation cannot manufacture provenance. (Warrant conservation.)
7. Contradiction must survive storage and retrieval.
8. Incomplete retrieval must be visible as degraded sufficiency.
9. Epistemic policy and action policy are separate.
10. Equivalent evidence must yield equivalent warrant independent of storage substrate.

Endogenous operations include retrieval, summarization, reflection, dreaming, consolidation, reranking, repetition, same-evidence majority, graph propagation, and LLM critique. They may reorganize. They MUST NOT raise verification class.

Derivation may preserve or reduce warrant. It MUST NOT raise verification class or mint provenance absent from its premises.

Lineage independence: increasing the number of derived representations within one `lineage_id` MUST NOT increase independent-evidence count.

## Conformance tests

A store adapter is not conforming because it serializes the schema. It MUST pass:

1. Reinforcement invariance — repeating an unsupported assertion cannot raise verification class.
2. Fork preservation — contradictory assertions remain independently recoverable.
3. Compression monotonicity — summarization cannot increase warrant or verification class.
4. Retrieval completeness awareness — missing possible contradictors ⇒ `sufficiency=DEGRADED`, not silent agreement.
5. Persona non-authority — an agent’s self-description does not establish facts about itself.
6. Warrant conservation — derived claims cannot outrank premises.
7. Lineage independence — derived copies of one source do not count as independent evidence.
8. Temporal invalidation — fresh contrary evidence can defeat prior acceptance without deleting history.
9. Policy reproducibility — same view + policy version + `evaluated_at` ⇒ same `WarrantView`.
10. Store independence — the same fixture loaded through conforming adapters yields equivalent normalized `WarrantView`s.

Test 10 uses the canonical fixtures in `docs/implementer/fixtures/` (and the same objects in `protocol/fixtures.py`). Run each adapter → `EvidenceView` → `warrant_now()` → compare normalized `WarrantView`. Material difference means a lost field or an underspecified interchange.

Additional behavioral pack: `protocol/laundering.py`. It is not part of the 26-golden lock. It must still agree across the two reference evaluators.

## Out of scope for v0.1

- Choosing a persistence engine
- Agent persona / MEMORY.md format
- Action-policy contents (thresholds, auth, reversibility)
- Graphiti / MindGraph / KIP as transition authorities
- A shipped MCP server (sketch only: `historical/docs/MCP_CONTRACT.md`)
- Any operation that writes epistemic truth back into a store

## Reference implementation

1. `protocol/fixtures.py` — canonical bundles
2. `protocol/classify.py` — shared check classification
3. `protocol/warrant.py` / `protocol/warrant_b.py` — two control flows, same five axes
4. `protocol/sqlite_adapter.py` / `protocol/json_adapter.py` — substrates (warrant is never written back)
5. `protocol/graphiti_adapter.py` — fake Graphiti-shaped records for the frozen suite
6. `tests/test_conformance.py` — tests 1–10 plus separate `may_act`

Live, not part of the 26-golden lock:

- `protocol/graphiti_client_adapter.py` / `protocol/mem0_adapter.py`
- notes: `docs/implementer/LIVE_ADAPTERS.md`

Gate: `python3 tests/test_conformance.py && python3 tests/test_goldens.py`

Frozen artifacts (do not edit to match a store):

- `protocol/fixtures.py`
- `protocol/pathological.py` / `protocol/pathological_fixtures.py`
- `protocol/classify.py`, `protocol/warrant.py`, `protocol/types.py`
- `tests/golden_warrantviews/`
- `RELEASE.lock.json` (fixture + evaluator + golden hashes)

Integration pin: Graphiti `0.30.2`. Live `graphiti-core` is an external-substrate test. v0.1 does not adapt to Graphiti.
