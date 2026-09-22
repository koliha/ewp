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
                  subjects[] optional
omitted_sources[]
retrieval_scope   default complete
degraded          default false
freshness_policy_seconds
adapter_meta      ignore for axes; may record lineage_basis
subjects[]        optional v0.2 subject ids (customer-42, …)
```

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

## Axes (output)

```
acceptance     UNACCEPTED | TENTATIVE | ACCEPTED
conflict       NONE | OPEN | RESOLVED
verification   NONE | INDIRECT | EXTERNAL | HUMAN
currency       CURRENT | STALE | SUPERSEDED
sufficiency    SUFFICIENT | INSUFFICIENT | DEGRADED
```

Also record `policy_id=reference-v1`, `policy_version=reference-v1`, and `evaluated_at`. Do not treat `strength` as required.

This file is the normative serialization of the interchange. The nested `WarrantView` block in `docs/PROTOCOL_v0.1.md` is a conceptual view of the same axes plus diagnostics. Compare independent implementations on the five axes only.

`checks[].result` is required input. Classify using method, origin, result, scope/subjects, and availability at `evaluated_at` together — see `POLICY.md`.
