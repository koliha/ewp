# EvidenceView and WarrantView axes

## EvidenceView (input)

```
view_id
proposition_id
assertions[]      assertion_id, proposition_id, text, asserted_by,
                  assertion_confidence, source, asserted_at
evidence[]        evidence_id, proposition_id, polarity (supports|opposes),
                  source, content, observed_at
lineage[]         from_id, to_id, kind (derived_from|supersedes|superseded_by|parent_source)
conflicts[]       conflict_id, proposition_ids[], status (open|resolved), note
checks[]          check_id, method, scope, source, observed_at,
                  result (supports|opposes|inconclusive),
                  subjects[]  declared subject ids; may be empty
omitted_sources[]
retrieval_scope   default complete
degraded          default false
freshness_policy_seconds   non-negative integer
adapter_meta      ignore for axes; may record lineage_basis
subjects[]        declared subject ids of the proposition; may be empty
```

The enums in parentheses are closed. A value outside them makes the view invalid: refuse it, do not evaluate it.

The view is bounded: every assertion and evidence `proposition_id` equals the view's (or is `proposition_id:<suffix>`), and every conflict's `proposition_ids` include it. `subjects` are JSON arrays of non-empty strings, never a bare string. `freshness_policy_seconds` is a non-negative integer (`0` is valid; booleans are not integers). `degraded` is a boolean. A missing field takes the default shown; a present value is never replaced because it is falsy. `invalid/` has one view per rule.

## SourceRef

```
source_id
lineage_id
origin_type
origin_locator
snapshot_id
content_hash
observed_at
extractor_id?
parent_source_id?
```

## WarrantView (normative output)

```
protocol_version   EWP-0.2.0
proposition_id
view_id
policy_id          reference-v2
policy_version     reference-v2
evaluated_at
warrant {
  acceptance     UNACCEPTED | TENTATIVE | ACCEPTED
  conflict       NONE | OPEN | RESOLVED
  verification   NONE | INDIRECT | EXTERNAL | HUMAN
  currency       CURRENT | STALE | SUPERSEDED
  sufficiency    SUFFICIENT | INSUFFICIENT | DEGRADED
}
```

This is the interchange contract and the equality contract. Compare independent implementations on the five axes under the same `protocol_version`, `policy_id`/`policy_version`, and `evaluated_at`.

Not normative: `strength`, `rationale_codes`, and the diagnostic arrays of the reference `WarrantView` (evidence ids, lineage count, freshest check, conflict ids, lineage lists). An implementation may emit them, name its reasons differently, or omit them, and still conform.

`checks[].result` is required input. Classify using method, origin, result, subjects, and availability at `evaluated_at` together — see `POLICY.md`.

Each `expected/*.json` file records the five axes plus `protocol_version`, `policy_version`, and `evaluated_at`.
