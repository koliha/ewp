# Open questions after EWP-0.2.0

Cases the 0.2.0 model cannot express cleanly. None of them is in the locked packs, and none changes `reference-v2`. Each would become a fixture first; a new primitive is added only if that fixture cannot be expressed with the current ones.

## 1. Retraction without replacement

**Status: UNRESOLVED — candidate primitive for a later version.**

```
T1  Alice asserts P.
T2  Alice explicitly withdraws her assertion of P.
    No one asserts not-P. There is no successor proposition.
```

What a correct model must say:

- Alice's original assertion stays recoverable.
- The withdrawal is not evidence for not-P.
- The withdrawal does not count as support for P.
- The withdrawal is not supersession.
- Bob's independent assertion of P is untouched: Alice withdrew *her* claim, not the proposition.

What `reference-v2` says for each available encoding (Alice and Bob both assert P from `turn` sources; evaluated after T2):

| Encoding | acceptance | conflict | currency | Problem |
|---|---|---|---|---|
| Before the withdrawal | TENTATIVE | NONE | CURRENT | — |
| Opposing evidence from Alice | TENTATIVE | NONE | CURRENT | Invisible on the axes: assertions carry no polarity, so one opposing item against bare assertions opens nothing |
| Same, where Alice also had supporting evidence | TENTATIVE | OPEN | CURRENT | Reads as a live dispute about not-P, not a withdrawal |
| New snapshot without Alice's assertion | TENTATIVE | NONE | CURRENT | Correct axes, but the withdrawal itself is gone from the current view; it survives only as the difference between snapshots |
| Same, when Alice was the only asserter | UNACCEPTED | NONE | CURRENT | Correct axes, same loss |
| `superseded_by` edge to a placeholder id | TENTATIVE | NONE | SUPERSEDED | Invents a successor; supersedes Bob's claim too |
| Withdrawal recorded as an assertion | TENTATIVE | NONE | CURRENT | Counts as grounds for P |
| Withdrawal assertion as the only record | TENTATIVE | NONE | CURRENT | A pure withdrawal lifts P from UNACCEPTED to TENTATIVE |

Dropping the assertion comes closest, at the cost of the audit trail. The others are wrong in some way.

Three different speech acts are involved, and they should not share one field:

| Act | What it is about |
|---|---|
| assert P | the proposition |
| deny P (assert not-P) | the proposition, opposite stance |
| withdraw assertion A | a specific assertion, by id |

Deny is assertion polarity (the known limit in `POLICY.md`). Withdraw is an operation on an assertion's identity. A likely shape is a separate record, something like `{target_assertion_id, kind: retract, source, observed_at}`, not a status field on the assertion:

- Stored records are immutable (`EWP_REFUSE_IMMUTABLE_RECORD`), so marking an assertion "retracted" would mean editing it. A new record pointing at it fits the append-only ledger.
- The record has its own `observed_at`, so replaying an evaluation before T2 still shows the assertion as live. Conflict rows and lineage edges carry no timestamp today, so they cannot give that.

Let the fixture decide the shape.

## 2. Assertion polarity

**Status: known limit in 0.2.0 (`POLICY.md`, `CHANGELOG.md`).**

Assertions have no stance. Every available assertion counts as grounds for `TENTATIVE`, including one that denies the proposition. Direction is carried only by evidence `polarity` and check `result`. This interacts with retraction (above) but is a separate question.

## 3. Validity time

**Status: open.**

EWP separates when a record was observed (`observed_at`), when warrant is evaluated (`evaluated_at`), how old a check may be (`freshness_policy_seconds`), and whether a proposition was replaced (`superseded_by`). It has no field for when a proposition held in the world.

```
P = "Alice is CEO of Acme"
evidence: an audited filing, observed yesterday, says Alice was CEO from 2022 to 2024
```

That evidence is verified, fresh, historically valid, and says nothing about now. Freshness cannot express "true then, not now". Today the answer is to scope the proposition itself (`P-alice-ceo-2022-2024`) rather than to add validity intervals. Add a validity model only when a fixture shows proposition scoping cannot represent a real case.

## 4. Timestamps on conflicts and lineage

**Status: known limit in 0.2.0.**

Conflict rows and lineage edges carry no timestamp, so they are not filtered by availability at T: an edge recorded later still applies when replaying an earlier T. A retraction record (1) would need to avoid the same gap.

## 5. Ingest authority vs. action-policy authority

**Status: open; consistent with 0.2.0 as documented.**

In the MCP façade, a caller holding the ingest role may also supply a `risk_policy` to `ewp_may_act`, including one that relaxes the high-risk gate. That is deliberate and documented (operator-only), and tested. But the authority to add evidence and the authority to change what evidence may be used for are different things, the same split EWP draws between warrant and action. A later version could give them separate capabilities (an ingest token and an action-policy token, or action policy fixed at server start).

## Not planned

These come up when comparing EWP with belief-propagating memory stores. They stay out of the kernel:

- **Propagated credence** (a mean and variance computed over support/contradiction edges). That is a store's own projection. An adapter may carry it in `adapter_meta`; it never becomes an axis. EWP already separates "little evidence" (`sufficiency=INSUFFICIENT`) from "strong evidence on both sides" (`conflict=OPEN`).
- **Source-credibility tiers.** Reputation is not verification (`POLICY.md`: `EXTERNAL` classifies the channel, not source quality). A later policy could let source quality affect acceptance; it would never make a check `EXTERNAL`.
- **Automatic time decay** by source type. Currency is computed from the class-conferring check's age at `evaluated_at` under one declared freshness window.
