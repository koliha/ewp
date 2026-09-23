# EWP Conformance

An adapter is not conformant because it serializes the schema. It must survive the fixture packs and produce the golden `WarrantView`s for protocol `EWP-0.2.0`, policy `reference-v2`.

The five axes are the interchange contract, compared under the same `protocol_version`, policy identity, and `evaluated_at`. `strength` and `rationale_codes` are non-normative diagnostics of the reference evaluator. See `docs/DESIGN_NOTE.md` and `docs/implementer/SCHEMA.md`.

## Packs

| Pack | Where | Count | Locked |
|---|---|---|---|
| Canonical | `protocol/fixtures.py` | 14 | goldens + implementer pack |
| Pathological | `protocol/pathological.py` | 12 | goldens + implementer pack |
| Hardening | `protocol/laundering.py` | 24 | implementer pack |

The hardening pack tries to break method-only “verification,” latest-row supersession, incomplete-view optimism, unused `check.result`, implied conflict, human-method laundering, endogenous freshness refresh, subject binding (`customer-42` vs `customer-99`, `customer-42` vs `invoice-999`, `server01` vs `customer-42`, omitted check subjects, a shared subject that should verify), future-dated and unparsable check times at T, and a `superseded_by` edge between unrelated propositions.

All 50 fixtures and their expected axes live in `docs/implementer/`. The reference evaluator, the second evaluator (`protocol/warrant_b.py`), and an independent third evaluator (`docs/implementer/third_eval.py`, written from `POLICY.md` / `policy.json` only) must all agree on them.

## Store independence

`tests/test_adapter_roundtrip.py` runs every fixture through SQLite, JSON, fake Graphiti, and Mem0 (fake client), and requires identical normative axes. A field an adapter forgets to persist shows up here as `WARRANT_MISMATCH`. The live Graphiti client adapter is additionally checked for `subjects[]` preservation in its parked sidecar.

Live Graphiti / Mem0 mappings (`protocol/graphiti_client_adapter.py`, `protocol/mem0_adapter.py`, `tests/test_live_adapters.py`) are mapping tests. They do not validate `graphiti-core 0.30.2`.

The MCP façade (`protocol/mcp_server.py`, `tests/test_mcp.py`) is an integration boundary. Conformance of warrant is still the five axes. The server must not persist a `WarrantView` as evidence, must require the ingest role for every write, must not let an inline view authorize action, and must not infer `may_act` without an action.

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
Hardening: 24/24
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

`tests/report.py` prints `CONFORMANT` only when `tests/.last_ci.json` was written by a passing `tests/ci.py` on a tree with the same hashes. A stamp from before an edit reports `CLAIM_ONLY`.

## CI

```
python3 tests/ci.py
python3 tests/report.py
```

Changing a golden, the implementer pack, the policy text, or the evaluator requires a protocol or policy version change, then `python3 tests/ci.py --write-lock`.
