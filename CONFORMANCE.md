# EWP Conformance

An adapter is not conformant because it serializes the schema. It must survive the fixture packs and produce the golden `WarrantView`s for policy `reference-v1`.

The five axes are the interchange contract. `strength` is a non-normative convenience of `reference-v1`. See `docs/DESIGN_NOTE.md`.

A second pack (`protocol/laundering.py`, `tests/test_laundering.py`) tries to break method-only “verification,” latest-row supersession, incomplete-view optimism, unused `check.result`, implied conflict, human-method laundering, endogenous freshness refresh, identifier-family scope mismatch (`customer-42` vs `customer-99`), and future-dated checks at T. It is not part of the frozen 26-golden lock.

Live Graphiti / Mem0 mappings (`protocol/graphiti_client_adapter.py`, `protocol/mem0_adapter.py`, `tests/test_live_adapters.py`) are mapping tests. They are not a substitute for the 26-golden lock and do not validate `graphiti-core 0.30.2`.

The MCP façade (`protocol/mcp_server.py`, `tests/test_mcp.py`) is an integration boundary. Conformance of warrant is still the five axes. The server must not persist a `WarrantView` as evidence and must not infer `may_act` without an action.

## Failure classes

| Class | Meaning |
|---|---|
| `INGEST_LOSS` | The store did not preserve assertions, sources, lineage, checks, or conflicts. |
| `ADAPTER_MAP_LOSS` | The store has the records; the adapter did not reconstruct `EvidenceView`. |
| `WARRANT_MISMATCH` | Reconstructed view yields a different normalized `WarrantView` than the golden. |
| `RETRIEVAL_LOSS` | Search omitted evidence and did not mark `sufficiency=DEGRADED`. |
| `EXPECTED_DIVERGENCE` | Observation, not a failure. Store-local “current fact” disagrees with `warrant_now`. That is the protocol working. |

## Report shape

```
Epistemic Warrant Protocol EWP-0.2.0
Policy reference-v1
Fixture set sha256: …
Evaluator set sha256: …
Golden set sha256: …
Adapter: graphiti-core 0.30.2
Canonical: 14/14
Pathological: 12/12
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

## CI

```
python3 tests/ci.py
python3 tests/report.py
```

Changing a golden or the evaluator requires a protocol or policy version bump, then `python3 tests/ci.py --write-lock`.
