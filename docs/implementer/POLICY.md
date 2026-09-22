# Policy `reference-v1`

Named policy. Not the protocol. Policy id: `reference-v1`. Version string: `reference-v1`.

Evaluate only the bounded view you were given. Do not fetch more evidence. Do not infer hidden common cause between sources. Do not treat silence as a search of the store.

## Check classification

Classify each verification check, then take the highest class present.

Order, high to low: `HUMAN` > `EXTERNAL` > `INDIRECT` > `NONE`.

Human methods: `human_attestation`, `human_review`.

External methods: `tool_observation`, `external_clock`, `document_quote`, `independent_reproduction`, `vendor_documentation`, `winrm`, `external_api`.

Indirect methods: `inference`, `extract`, `derived`, `model_introspection`.

Trusted origins (allowlist): `tool`, `document`, `human`, `api`, `vendor`, `sensor`.

Endogenous origins: `extract`, `turn`, `derived`, `summary`, `model_introspection`.

Unknown origins (`episode`, `graph`, `agent`, …) are untrusted.

- Human or external method **and** trusted origin **and not** endogenous → `HUMAN` or `EXTERNAL`.
- Human or external method **and** untrusted or endogenous origin → `INDIRECT`.
- Indirect method → `INDIRECT`.
- Unknown method → `NONE`.
- `result=inconclusive` cannot raise `HUMAN` or `EXTERNAL`. Cap at `INDIRECT`.
- If `scope` names an entity in the same family as the view (`server*`, `host*`, `node*`, `device*`, `serial*`) and that token is not the one in the view → cap that check at `INDIRECT`. A scope that is only an inspection surface (`dashboard_screenshot`) does not cap.
- `result=opposes` still classifies the check. Polarity is a conflict input, not a reason to ignore the check.

A later check does not supersede an earlier one by timestamp alone. Compare `observed_at` as instants, not as raw strings (`Z` vs `+00:00`).

Derivation without a new trusted-origin check cannot raise class. A new tool or human check on the conclusion is new evidence, not manufactured provenance.

## Conflict

- Any conflict with `status=open` → `OPEN`
- Else both polarities present in evidence (`supports` and `opposes`) or in checks (`result=supports` and `result=opposes`) → `OPEN`
- Else any with `status=resolved` → `RESOLVED`
- Else `NONE`

Missing `Conflict` rows must not hide a live opposition that is already in the view.

## Currency

- Any lineage edge of kind `superseded_by` that applies to this proposition → `SUPERSEDED`
- Else, if the newest check *that confers the chosen verification class* is older than `freshness_policy_seconds` at `evaluated_at` → `STALE`
- Else `CURRENT`

Age uses that check’s `observed_at` parsed as an instant. A later untrusted or endogenous check cannot refresh `EXTERNAL` or `HUMAN` currency.

## Sufficiency

- `degraded` is true, or `omitted_sources` is non-empty, or `retrieval_scope` is not `complete` → `DEGRADED`
- No assertions, no evidence, no checks → `INSUFFICIENT`
- Else `SUFFICIENT`

`DEGRADED` means the view is bounded. It is not a proof that no contradictor exists. It also blocks `ACCEPTED`.

## Acceptance

- No assertions and no supporting evidence → `UNACCEPTED`
- Else if verification is `EXTERNAL` or `HUMAN`, conflict is not `OPEN`, currency is not `SUPERSEDED`, sufficiency is `SUFFICIENT` (not `DEGRADED`, not `INSUFFICIENT`), the class-conferring check is not stale, and no `EXTERNAL`/`HUMAN` check has `result=opposes` → `ACCEPTED`
- Else `TENTATIVE`

Incomplete retrieval cannot produce `ACCEPTED`. That is the policy reading of “losing evidence must not raise warrant.”

Acceptance is a policy judgment over the other axes. It is not a sixth independent observation.

`strength` is a non-normative convenience. Do not branch on it.

## Lineage count (reported, not an axis)

Unique `lineage_id` values on assertions, evidence, and checks. Copies and summaries that share a `lineage_id` count as one.

Independence is whatever the view claims. Do not merge two lineage ids because the text looks similar. Do not split one lineage because the wording differs.

## What this policy does not do

- Infer that two documents secretly share a press release
- Treat `ORDER BY time DESC LIMIT 1` as supersession
- Raise verification because many agents repeated the same sentence
- Treat `result=opposes` or `result=inconclusive` as a supporting verification badge
- Treat an unknown origin as trusted
- Authorize action
