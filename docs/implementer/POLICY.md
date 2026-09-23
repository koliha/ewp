# Policy `reference-v2`

Named policy. Not the protocol. Protocol: `EWP-0.2.0`. Policy id: `reference-v2`. Version string: `reference-v2`.

`reference-v1` is the EWP-0.1.0 policy. `reference-v2` changes its subject binding, supersession scope, availability, and input validation (below), so it carries a new name. An evaluator refuses a policy identity it does not implement.

Evaluate only the bounded view you were given. Do not fetch more evidence. Do not infer hidden common cause between sources. Do not treat silence as a search of the store.

## Input validation

These enums are closed:

- evidence `polarity`: `supports`, `opposes`
- check `result`: `supports`, `opposes`, `inconclusive`
- conflict `status`: `open`, `resolved`
- lineage `kind`: `derived_from`, `supersedes`, `superseded_by`, `parent_source`

A view with any other value is invalid. Refuse it; do not evaluate it. An unknown `result` must not classify like `supports`, an unknown `status` must not read as no conflict, and an unknown `polarity` must not silently drop opposition.

## Availability at T

A record is available at `evaluated_at` only if its instant (`asserted_at` for assertions, `observed_at` for evidence and checks) parses and is not after `evaluated_at`. Missing or unparsable instants are not available. Unavailable records cannot confer class, refresh currency, open conflict, count toward sufficiency or lineage, or support acceptance. Compare instants, not raw strings (`Z` vs `+00:00`; naive values are UTC).

## Check classification

Classify each verification check, then take the highest class present.

Order, high to low: `HUMAN` > `EXTERNAL` > `INDIRECT` > `NONE`.

Human methods: `human_attestation`, `human_review`.

External methods: `tool_observation`, `external_clock`, `document_quote`, `independent_reproduction`, `vendor_documentation`, `winrm`, `external_api`.

Indirect methods: `inference`, `extract`, `derived`, `model_introspection`.

Trusted origins (allowlist): `tool`, `document`, `human`, `api`, `vendor`, `sensor`.

Endogenous origins: `extract`, `turn`, `derived`, `summary`, `model_introspection`.

Unknown origins (`episode`, `graph`, `agent`, `inline:tool`, …) are untrusted.

- Not available at T → `NONE`.
- Human or external method **and** trusted origin **and not** endogenous → `HUMAN` or `EXTERNAL`.
- Human or external method **and** untrusted or endogenous origin → `INDIRECT`.
- Indirect method → `INDIRECT`.
- Unknown method → `NONE`.
- `result=inconclusive` cannot raise `HUMAN` or `EXTERNAL`. Cap at `INDIRECT`.
- A check whose subjects do not bind to the view (below) cannot raise `HUMAN` or `EXTERNAL`. Cap at `INDIRECT`.
- `result=opposes` still classifies the check. Polarity is a conflict input, not a reason to ignore the check.

A later check does not supersede an earlier one by timestamp alone.

Derivation without a new trusted-origin check cannot raise class. A new tool or human check on the conclusion is new evidence, not manufactured provenance.

## Subject binding

Identity is declared `subjects[]` on the view and on each check, compared as exact, case-insensitive ids. `scope` is an inspection surface (`dashboard_screenshot`, a query name) and is never scraped for identifiers.

- Neither the check nor the view declares subjects → the check binds.
- Both declare subjects and share at least one id → the check binds.
- Anything else → the check does not bind: disjoint ids (`server01` vs `server02`, `customer-42` vs `customer-99`, `customer-42` vs `invoice-999`, `server01` vs `customer-42`), or only one side declares subjects.

There is no family inference. A proposition about several entities declares all of them; a check on any one of them binds.

## Conflict

- Any conflict with `status=open` → `OPEN`
- Else both polarities present in available evidence (`supports` and `opposes`) or in available checks (`result=supports` and `result=opposes`) → `OPEN`
- Else any with `status=resolved` → `RESOLVED`
- Else `NONE`

Missing `Conflict` rows must not hide a live opposition that is already in the view. Conflict rows carry no timestamp and are not filtered by availability.

## Currency

- Any lineage edge of kind `superseded_by` whose `from_id` is the view's `proposition_id`, or a variant `proposition_id:<suffix>` → `SUPERSEDED`. Edges between other propositions do not apply. Lineage edges carry no timestamp and are not filtered by availability.
- Else, if the newest check *that confers the chosen verification class* is older than `freshness_policy_seconds` at `evaluated_at` → `STALE`
- Else `CURRENT`

Age uses that check’s `observed_at` parsed as an instant. A later untrusted or endogenous check cannot refresh `EXTERNAL` or `HUMAN` currency.

## Sufficiency

- `degraded` is true, or `omitted_sources` is non-empty, or `retrieval_scope` is not `complete` → `DEGRADED`
- No available assertions, evidence, or checks → `INSUFFICIENT`
- Else `SUFFICIENT`

`DEGRADED` means the view is bounded. It is not a proof that no contradictor exists. It also blocks `ACCEPTED`.

## Acceptance

- No available assertions and no available supporting evidence → `UNACCEPTED`
- Else if verification is `EXTERNAL` or `HUMAN`, conflict is not `OPEN`, currency is not `SUPERSEDED`, sufficiency is `SUFFICIENT` (not `DEGRADED`, not `INSUFFICIENT`), the class-conferring check is not stale, and no `EXTERNAL`/`HUMAN` check has `result=opposes` → `ACCEPTED`
- Else `TENTATIVE`

Incomplete retrieval cannot produce `ACCEPTED`. That is the policy reading of “losing evidence must not raise warrant.”

Acceptance is a policy judgment over the other axes. It is not a sixth independent observation.

`strength` and `rationale_codes` are non-normative. Do not branch on them, and do not compare implementations on them.

## Lineage count (reported, not an axis)

Unique `lineage_id` values on available assertions, evidence, and checks. Copies and summaries that share a `lineage_id` count as one.

Independence is whatever the view claims. Do not merge two lineage ids because the text looks similar. Do not split one lineage because the wording differs.

## What this policy does not do

- Infer that two documents secretly share a press release
- Treat `ORDER BY time DESC LIMIT 1` as supersession
- Raise verification because many agents repeated the same sentence
- Treat `result=opposes` or `result=inconclusive` as a supporting verification badge
- Treat an unknown origin as trusted
- Guess a subject from text, or treat two ids as the same entity because they share a prefix
- Evaluate a value outside a closed enum
- Authorize action
