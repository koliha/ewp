# Epistemic Warrant Protocol (EWP) 0.2.0

Status: current contract. Protocol `EWP-0.2.0`, reference policy `reference-v2`. The EWP-0.1.0 contract is `docs/EWP_v0.1.0.pdf` (and this file's history, formerly `docs/PROTOCOL_v0.1.md`); `reference-v1` names the 0.1 policy and is not accepted by the 0.2 evaluator.

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
same protocol_version + same evidence_view + same policy_id/version + same evaluated_at
  => same normative WarrantView
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

Stores MUST NOT present a local projection as universal belief. Stores MUST preserve every field in `docs/implementer/SCHEMA.md`, including `subjects[]`, completeness, and freshness, across a write/read round trip.

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
  method             # tool_observation | external_clock | document_quote | human_attestation | independent_reproduction | …
  scope              # what was actually inspected (opaque text)
  source             # SourceRef
  observed_at
  result             # supports | opposes | inconclusive
  subjects[]         # declared subject ids this check is about; may be empty
}
```

Verification is evidence with method, scope, source, time, and `result`. It is not a badge on a proposition.

`result` is normative:

- `supports` — the check bears on P in the supporting direction
- `opposes` — the check bears on P against it; this opens `conflict=OPEN` and blocks `ACCEPTED`
- `inconclusive` — a check ran; it cannot raise verification class to `EXTERNAL` or `HUMAN`

Method name is not enough. Only origins `tool`, `document`, `human`, `api`, `vendor`, `sensor` may raise `HUMAN` or `EXTERNAL`. If `source.origin_type` is endogenous or unknown (`extract`, `turn`, `derived`, `summary`, `model_introspection`, `episode`, …), a human or external method is capped at `INDIRECT`.

### Closed enums

`polarity`, `result`, conflict `status`, and lineage `kind` are closed enums (`docs/implementer/SCHEMA.md`). A view carrying any other value is invalid. Implementations MUST refuse it rather than evaluate it: an unknown value may not be read as `supports`, as "no conflict", or be silently dropped.

### WarrantView

Axes are independent. They MUST NOT be collapsed into one exclusive enum.

The normative serialization is `docs/implementer/SCHEMA.md` and `WarrantView.normative()`:

```
protocol_version
proposition_id
view_id
policy_id
policy_version
evaluated_at
warrant {
  acceptance     UNACCEPTED | TENTATIVE | ACCEPTED
  conflict       NONE | OPEN | RESOLVED
  verification   NONE | INDIRECT | EXTERNAL | HUMAN
  currency       CURRENT | STALE | SUPERSEDED
  sufficiency    SUFFICIENT | INSUFFICIENT | DEGRADED
}
```

Two conforming implementations are compared on that object only. `rationale_codes`, `strength`, and the diagnostic arrays below are reference-implementation output. Implementations may use a different reason taxonomy and still conform.

```
diagnostics (reference implementation, non-normative) {
  strength, rationale_codes[]
  supporting_evidence_ids[], opposing_evidence_ids[], independent_lineage_count
  checks[], freshest_check, stale
  open_conflicts[], resolved_conflicts[], omitted_sources[]
  derived_from[], supersedes[], superseded_by[]
}
```

`warrant.*` is computed. It is not persisted as epistemic truth.

## Identity

```
protocol_version  = EWP-0.2.0
Policy.policy_id  = reference-v2
Policy.version    = reference-v2
```

`WarrantView.protocol_version`, `policy_id`, and `policy_version` MUST echo those strings. An evaluator MUST refuse a policy identity it does not implement. When a policy's judgments change, its name changes.

## Conflict

`conflict=OPEN` when any of:

- a `Conflict` row has `status=open`
- evidence contains both `supports` and `opposes`
- checks contain both `result=supports` and `result=opposes`

A missing `Conflict` row must not hide opposition already present in the view.

## Currency

- a lineage edge `superseded_by` whose `from_id` is this proposition, or a variant `proposition_id:<suffix>` → `SUPERSEDED`. Edges between other propositions do not apply.
- a record with `observed_at` after `evaluated_at`, or with a missing or unparsable instant, is not available at T and cannot confer class, refresh currency, or open conflict
- else the newest check that confers the chosen verification class is older than `freshness_policy_seconds` at `evaluated_at` → `STALE`
- else `CURRENT`

A later endogenous check cannot refresh `EXTERNAL` or `HUMAN` currency.

Conflict rows and lineage edges carry no timestamp in 0.2.0, so they are not filtered by availability at T. An edge recorded later still applies when replaying an earlier T. This is a known limit; see `CHANGELOG.md`.

## Subjects

`VerificationCheck.scope` is opaque text and is never scraped for identifiers. Identity is declared `subjects[]`, on the view and on each check, compared as exact ids:

- neither declares subjects → the check applies
- both declare subjects and share at least one → the check applies
- otherwise (disjoint ids, or only one side declares) → the check cannot raise `HUMAN` or `EXTERNAL`

There is no family inference: `customer-42` vs `invoice-999` and `server01` vs `customer-42` are both mismatches. A proposition about several entities declares all of them. Adapters SHOULD populate `subjects` whenever the store has a real subject key.

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

## Action gate

`may_act` consumes a `WarrantView`, an `Action {risk: low|medium|high, reversible}`, and a `RiskPolicy`. An unknown risk level is refused. A `SUPERSEDED` proposition is `DENY` for high risk and at least `REQUIRE_CONFIRMATION` otherwise. The action policy belongs to the operator, not to the agent being gated.

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
9. Policy reproducibility — same protocol + view + policy + `evaluated_at` ⇒ same normative `WarrantView`.
10. Store independence — every fixture (canonical, pathological, hardening) loaded through a conforming adapter yields the same normative axes.

Test 10 runs all 50 fixtures in `docs/implementer/fixtures/` through each adapter → `EvidenceView` → `warrant_now()` (`tests/test_adapter_roundtrip.py`). A difference means a lost field or an underspecified interchange.

## Out of scope for 0.2

- Choosing a persistence engine
- Agent persona / MEMORY.md format
- Action-policy contents beyond the reference gate (thresholds, auth)
- Graphiti / MindGraph / KIP as transition authorities
- Any operation that writes epistemic truth back into a store
- MCP Streamable HTTP (the shipped HTTP endpoint is plain JSON-RPC)

## Reference implementation

1. `protocol/fixtures.py`, `protocol/pathological.py`, `protocol/laundering.py` — canonical, pathological, and hardening fixtures
2. `protocol/classify.py` — validation, check classification, subject binding, supersession scope
3. `protocol/warrant.py` / `protocol/warrant_b.py` — two control flows, same five axes
4. `protocol/sqlite_adapter.py` / `protocol/json_adapter.py` — substrates (warrant is never written back; SQLite is append-only)
5. `protocol/graphiti_adapter.py` — fake Graphiti-shaped records
6. `protocol/graphiti_client_adapter.py` / `protocol/mem0_adapter.py` — live mappings (`docs/implementer/LIVE_ADAPTERS.md`)
7. `protocol/mcp_server.py` — MCP façade (`docs/MCP_CONTRACT.md`)
8. `docs/implementer/third_eval.py` — independent evaluator from the written policy only

Gate: `python3 tests/ci.py`

Locked artifacts (`RELEASE.lock.json`; change only with a version change, never to match a store):

- fixtures: `protocol/fixtures.py`, `protocol/pathological.py`, `protocol/laundering.py`
- evaluator: `protocol/classify.py`, `warrant.py`, `warrant_b.py`, `types.py`, `may_act.py`, `versions.py`
- policy: `docs/implementer/POLICY.md`, `docs/implementer/policy.json`
- goldens: `tests/golden_warrantviews/`
- implementer pack: `docs/implementer/fixtures/`, `docs/implementer/expected/`

Integration pin: Graphiti `0.30.2`. Live `graphiti-core` is an external-substrate test. The protocol does not adapt to Graphiti.
