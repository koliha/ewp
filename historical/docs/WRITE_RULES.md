# Write rules

## Two clocks

Every event stores `recorded_at` (host, always) and `occurred_at` (world time, nullable) plus `occurred_at_source`. Model-claimed time is never written as `recorded_at`. `clock_check` exists because this lineage already paid for that lesson.

## Who may write what

| Actor | May |
| --- | --- |
| Live agent | `claim_propose`, `claim_dispute`, `claim_explain`, `memory_context`, `session_*`, `clock_check` |
| Live agent with evidence event | `claim_verify` only if method is tool/human/document/clock — not introspection |
| Compaction / Dreaming / session_close | `claim_propose` and `propose_reinforcement` only. `confidence_delta_allowed=false`. |
| Human curator | all tools, including retract and merge |
| Graphiti extractor | write episodes and edges; never treat Graphiti current-fact as warrant |

## Compression

A compressor emits a `compression` event listing source claim ids and the fields it dropped. If `falsification_condition`, `last_verified_at`, or evidence refs are dropped, the packed view clamps confidence to ≤ 0.40 and appends `|compressed_without_warrant` to `confidence_basis`. The ledger row itself is unchanged.

## Contradiction

`claim_dispute` does not pick a winner. Status of both claims becomes `disputed`. Retrieval returns:

```
DISPUTED: A → X; B → ¬X; no resolving verification exists.
```

The model may explain that sentence. It may not emit “I used to think A, then I realized B” unless a `supersessions` row records that sequence.

## Method claims

“Verify timestamps” is a `procedure` claim:

```
proposition: Verify model-claimed time against host clock at session_open.
reason: model-supplied temporal context has been stale or absent.
observed_failures: [event_ids]
last_evaluated: ...
not_needed_when: host clock is injected into the system prompt and the model is forbidden from asserting dates.
```

Procedures expire too.

## Session close

The closing model proposes additions. A server-side extractor may draft claims from the transcript; they land as `proposed`. Nothing at close is `current` unless a `claim_verify` from a non-model source is attached by the runtime (e.g. the host actually ran a test).
