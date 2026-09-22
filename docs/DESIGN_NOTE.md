# EWP v0.1 design / conformance note

Not a protocol bump. This note separates what must stay still from what `reference-v1` happens to do.

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
3. Carry `policy_version` and `evaluated_at` on the result.
4. Count unique `lineage_id` values on assertions, evidence, and checks — not repetitions or summaries.
5. Refuse to let untrusted or endogenous origins raise `verification` to `EXTERNAL` or `HUMAN`. Only `tool|document|human|api|vendor|sensor` may. Check `result` and `scope` participate.
6. Mark incomplete retrieval `sufficiency=DEGRADED`.
7. Treat later timestamps as evidence of order, not as supersession.
8. Leave action authorization to a later gate.

Same view + same policy version + same `evaluated_at` → same five axes.

Incomplete retrieval (`sufficiency=DEGRADED`) cannot yield `acceptance=ACCEPTED` under `reference-v1`.

## Reference policy (`reference-v1`)

`protocol/warrant.py` is one function from those inputs to those axes. It may change without the protocol number changing, provided the normative fixtures still pass and any acceptance-rule change is called out as a policy revision.

Today it also computes a scalar `strength`. That field is **not** part of the interchange contract.

## Non-normative conveniences

- `strength` — derived commentary. A conforming implementation may omit it. Clients must not branch on `if strength > 0.8`.
- `rationale_codes` — debugging aids.
- Adapter metadata such as `lineage_basis=claimed_by_ingest`.

The interchange contract is the five axes plus policy identity and time.

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

Until independent implementations agree on the frozen *and* laundering packs, EWP is an architecture plus a reference function. Agreement on the five axes is what earns the word protocol.

The third implementation is the experiment. Give it only schema, policy prose, fixture inputs, and expected five-axis outputs. Do not give it `warrant.py`, helper names, or fixture-specific hints. Capture disagreements. Classify each:

| Kind | Meaning | What moves |
|---|---|---|
| Specification failure | The docs permit two reasonable readings | Clarify the boundary text. Protocol number stays unless a new primitive is required. |
| Reference-policy failure | The judgment is specified, and we no longer want it | Change `reference-v1` or mint `reference-v2`. Protocol number stays. |
| Implementation failure | The docs and policy are clear; the code missed them | Fix that evaluator. |

The proposition under test is not “EWP is true.” It is: given the same evidence, the same declared policy, and the same time, independent implementations cannot quietly invent different epistemic realities.

Pack: `docs/implementer/`.

## What is not in this note

No new axis. Adding an axis requires a fixture the current five cannot express. Removing ambiguity is a policy change, not an ontology change.
