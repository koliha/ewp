# EWP design / conformance note

Written for the v0.1 freeze and still accurate for the boundary/policy split. EWP-0.2.0 did not add axes. It made subject binding exact, scoped supersession to the proposition, made unavailable and malformed input explicit, and required adapters to round-trip every field. Those judgments changed, so the policy is now `reference-v2`. This note separates what must stay still from what `reference-v2` happens to do.

Boundary. Policy. Observations. Permission. Four things. None gets to wear the others' clothes.

## Four layers

| Layer | Owns | Must not own |
|---|---|---|
| Observations (store) | What is available to a view | What may be accepted |
| Provenance / ingest | Lineage *claims*, source identity | Warrant class |
| EWP boundary | Reproducible projection of a bounded view | Truth, hidden provenance inference, permission to act |
| Named policy | How those inputs become the five axes | Store schema, tool execution |
| Action policy | What the warrant may be used to do | Rewriting the axes |

EWP evaluates a bounded view. It does not establish that the bounded view is complete. `DEGRADED` means: the evaluator cannot treat silence as a search of everything.

## Normative boundary (must preserve)

An implementation of EWP must:

1. Accept an `EvidenceView`, a named policy version, and `evaluated_at`.
2. Emit the five axes: `acceptance`, `conflict`, `verification`, `currency`, `sufficiency`.
3. Carry `protocol_version`, `policy_id`, `policy_version`, and `evaluated_at` on the result, and refuse a policy identity it does not implement.
4. Count unique `lineage_id` values on assertions, evidence, and checks — not repetitions or summaries.
5. Refuse to let untrusted or endogenous origins raise `verification` to `EXTERNAL` or `HUMAN`. Only `tool|document|human|api|vendor|sensor` may. Check `result` and declared `subjects[]` participate.
6. Mark incomplete retrieval `sufficiency=DEGRADED`.
7. Treat later timestamps as evidence of order, not as supersession.
8. Leave action authorization to a later gate.
9. Refuse input outside the closed enums instead of evaluating it. An unknown value must fail closed.

Same protocol version + same view + same policy identity + same `evaluated_at` → same five axes.

Incomplete retrieval (`sufficiency=DEGRADED`) cannot yield `acceptance=ACCEPTED` under `reference-v2`.

## Reference policy (`reference-v2`)

`protocol/warrant.py` is one function from those inputs to those axes. Its implementation may change without the protocol number changing, provided the locked fixtures still pass. Any change to a judgment mints a new policy name: a policy name never changes meaning.

Today it also computes a scalar `strength`. That field is **not** part of the interchange contract.

## Non-normative conveniences

- `strength` — derived commentary. A conforming implementation may omit it. Clients must not branch on `if strength > 0.8`.
- `rationale_codes` — debugging aids. Two conforming implementations may name their reasons differently.
- Adapter metadata such as `lineage_basis=claimed_by_ingest`.

The interchange contract is the five axes plus protocol and policy identity and time.

Conformance is defined over the normative WarrantView axes, not over reference-policy convenience fields.

## Epistemic laundering

Epistemic laundering occurs when a system transforms internally generated or dependent evidence into a representation that appears independently corroborative, causing the resulting warrant to exceed what the underlying evidence supports.

| Kind | Pattern | What blocks it |
|---|---|---|
| Repetition | A → A' → A'' | `lineage_id` |
| Summarization | A → summary(A) → “confirmation” | `lineage_id` + `origin_type=extract` |
| Retrieval | A → retrieved(A) as a new hit | `DEGRADED` if the view is incomplete; same lineage if it is a transform |
| Verification | A → self-check(A) → “externally verified” | check origin and `result` cannot raise class on method name alone |

A check whose `method` is `document_quote` or `human_attestation` is not `EXTERNAL`/`HUMAN` if its `source.origin_type` is `extract`, `turn`, `summary`, or another endogenous origin. `result=inconclusive` cannot raise those classes either. Trusting the method string is a conformance failure.

Honest tool observation may share a lineage with the assertion when the origin *is* the observation (`origin_type=tool`). That is not laundering.

## Conformance failures this note names

- Epistemic laundering (especially verification laundering)
- Lost contradiction / incomplete-view optimism
- False supersession (`ORDER BY timestamp DESC LIMIT 1`)
- Provenance laundering (claimed independence treated as established independence)
- Scalar collapse (`strength` used as authorization)

## Interoperability test

Not: one evaluator, two stores.

The protocol test:

```
input view + policy.json + evaluated_at
        ↓
implementation A ── five axes
implementation B ── five axes
        ↓
identical axes
```

`protocol/warrant.py` and `protocol/warrant_b.py` are two control flows. `tests/test_laundering.py` compares them. A naive evaluator that trusts `method` alone must *disagree* on `launder_verification`.

Until independent implementations agree on all 50 fixtures (canonical, pathological, hardening), EWP is an architecture plus a reference function. Agreement on the five axes is what earns the word protocol. `docs/implementer/third_eval.py` is the first such implementation, written from the pack alone.

The third implementation is the experiment. Give it only schema, policy prose, fixture inputs, and expected five-axis outputs. Do not give it `warrant.py`, helper names, or fixture-specific hints. Capture disagreements. Classify each:

| Kind | Meaning | What moves |
|---|---|---|
| Specification failure | The docs permit two reasonable readings | Clarify the boundary text. Protocol number stays unless a new primitive is required. |
| Reference-policy failure | The judgment is specified, and we no longer want it | Mint a new policy name (`reference-v3`). Protocol number stays. |
| Implementation failure | The docs and policy are clear; the code missed them | Fix that evaluator. |

The proposition under test is not “EWP is true.” It is: given the same evidence, the same declared policy, and the same time, independent implementations cannot quietly invent different epistemic realities.

Pack: `docs/implementer/`.

## What is not in this note

No new axis. Adding an axis requires a fixture the current five cannot express. Removing ambiguity is a policy change, not an ontology change.
