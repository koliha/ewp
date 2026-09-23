# EWP Conformance

An adapter is not conformant because it serializes the schema. It must survive the fixture packs and produce the golden `WarrantView`s for protocol `EWP-0.2.0`, policy `reference-v2`.

The five axes are the interchange contract, compared under the same `protocol_version`, policy identity, and `evaluated_at`. `strength` and `rationale_codes` are non-normative diagnostics of the reference evaluator. See `docs/DESIGN_NOTE.md` and `docs/implementer/SCHEMA.md`.

## Packs

| Pack | Where | Count | Locked |
|---|---|---|---|
| Canonical | `ewp/fixtures.py` | 14 | goldens + implementer pack |
| Pathological | `ewp/pathological.py` | 12 | goldens + implementer pack |
| Hardening | `ewp/laundering.py` | 25 | implementer pack |
| Invalid (must be refused) | `ewp/laundering.py` `INVALID_PACK` | 12 | implementer pack |

The hardening pack tries to break method-only “verification,” latest-row supersession, incomplete-view optimism, unused `check.result`, implied conflict, human-method laundering, endogenous freshness refresh, subject binding (`customer-42` vs `customer-99`, `customer-42` vs `invoice-999`, `server01` vs `customer-42`, omitted check subjects, a shared subject that should verify), future-dated and unparsable check times at T, `freshness_policy_seconds=0`, and a `superseded_by` edge between unrelated propositions.

The invalid pack is one view per input rule (records about another proposition, a conflict that does not name the proposition, string `subjects`, negative or boolean freshness, a string `degraded`, each unknown enum value). The only conforming output is a refusal.

All 51 fixtures and their expected axes, and the 12 invalid views, live in `docs/implementer/`. The reference evaluator, the second evaluator (`ewp/warrant_b.py`), and an independent third evaluator (`docs/implementer/third_eval.py`, written from `POLICY.md` / `policy.json` only) must all agree on the axes and all refuse the invalid views.

## Store independence

`tests/test_adapter_roundtrip.py` runs every fixture through the JSON codec, SQLite, JSON, Mem0 (fake client), and fake Graphiti, and checks two things:

- **Axes**: identical normative axes (`WARRANT_MISMATCH` otherwise).
- **Fields**: the codec, SQLite, JSON, and Mem0 return every `SCHEMA.md` field unchanged. Graphiti's edge/episode model cannot hold record ids, `asserted_by`, `assertion_confidence`, or evidence content, and collapses identical assertions from one source; those losses are listed in the test (`GRAPHITI_FIELD_LOSSES`). Everything else — text, times, full source provenance, polarity, checks, conflicts, lineage, completeness, subjects, `view_id` — must come back.

The live Graphiti client adapter is **experimental**: its sidecar is checked for `subjects[]`, and its search path for the parked checks, but it is not validated against a real `graphiti-core`.

Live Graphiti / Mem0 mappings (`ewp/graphiti_client_adapter.py`, `ewp/mem0_adapter.py`, `tests/test_live_adapters.py`) are mapping tests. They do not validate `graphiti-core 0.30.2`.

The MCP façade (`ewp/mcp_server.py`, `tests/test_mcp.py`) is an integration boundary. Conformance of warrant is still the five axes. The server must not persist a `WarrantView` as evidence, must require the ingest role for every write, must not let an inline view authorize action, and must not infer `may_act` without an action.

## Failure classes

| Class | Meaning |
|---|---|
| `INGEST_LOSS` | The store did not preserve assertions, sources, lineage, checks, conflicts, subjects, or completeness. |
| `ADAPTER_MAP_LOSS` | The store has the records; the adapter did not reconstruct `EvidenceView`. |
| `WARRANT_MISMATCH` | Reconstructed view yields different normative axes than the reference. |
| `RETRIEVAL_LOSS` | Search omitted evidence and did not mark `sufficiency=DEGRADED`. |
| `EXPECTED_DIVERGENCE` | Observation, not a failure. Store-local “current fact” disagrees with `warrant_now`. That is the protocol working. |

## Report shape

```
Epistemic Warrant Protocol EWP-0.2.0
Policy reference-v2
fixture_set_sha256: …
evaluator_set_sha256: …
policy_set_sha256: …
golden_set_sha256: …
implementer_pack_sha256: …
Adapter: graphiti-core 0.30.2 — NOT VALIDATED
Canonical: 14/14
Pathological: 12/12
Hardening: 25/25
Invalid refused: 12/12
Result: CONFORMANT
```

or:

```
Result: NONCONFORMANT
p8-verify-survives-expiry
stage: RAW_VIEW
class: ADAPTER_MAP_LOSS
field: verification.checks[0]
expected: present
actual: missing
```

`tests/report.py` prints `CONFORMANT` only when `tests/.last_ci.json` was written by a passing `tests/ci.py` on the same tree: the protocol-lock hashes and a `ci_surface_sha256` over every file CI exercises (kernel, adapters, MCP server, tests, implementer pack, examples, workflow) must all match. A stamp from before any such edit reports `CLAIM_ONLY`.

## CI

```
python3 tests/ci.py
python3 tests/report.py
```

Changing a golden, the implementer pack, the policy text, or the evaluator requires a protocol or policy version change, then `python3 tests/ci.py --write-lock`.
