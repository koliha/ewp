# Changelog

## 0.2.0-docs — 2026-09-22

Documentation alignment only. Protocol number, policy id, and lock hashes unchanged.

- README freeze block, layout, OpenClaw, and status sections match EWP-0.2.0 and `RELEASE.lock.json`.
- `docs/MCP_CONTRACT.md` is the shipped façade; historical sketch stays superseded.
- `historical/README.md`, `docs/PLATFORMS.md` tool names, implementer intro, CONFORMANCE laundering list, and the v0.2 PDF agree with that split.

## 0.2.0 — 2026-09-22

Protocol bump. Policy identity stays `reference-v1`. Frozen 26 goldens unchanged; evaluator hash changes.

- Generic verification scope binding: identifier-shaped tokens (`customer-42`, `contract-123`) participate, not only `server|host|node|device|serial`. Optional `subjects[]` on the view and on each check is the store-neutral identity primitive; empty falls back to token extraction.
- A check with `observed_at` after `evaluated_at` is not available at T. It cannot confer class, refresh currency, open conflict, or produce `ACCEPTED`.
- SQLite persists view completeness (`omitted_sources`, `retrieval_scope`, `degraded`, freshness, subjects). Reconstructing a degraded view no longer defaults to `SUFFICIENT`.
- `WarrantView.normative()` is identity + time + five axes. The nested protocol-doc object is labeled conceptual; `docs/implementer/SCHEMA.md` is the serialization.
- `tests/report.py` is a claim printer. It requires `tests/.last_ci.json` from `tests/ci.py` before it will say `CONFORMANT`.
- Security: origin metadata is assumed established at the ingestion/adapter boundary. EWP does not authenticate evidence entering the ledger.
- Live Graphiti parked sidecar is found by `kind=ewp_parked` / `ewp-parked` content / `meta:{pid}` name, not by Graphiti's assigned episode UUID.
- Mem0 memories without `metadata.ewp.proposition_id` do not enter a proposition view.
- MCP façade ships: `python3 -m protocol.mcp_server`. Tools evaluate warrant, persist EvidenceViews, record checks, and gate `may_act`. Trusted origins require `ingest_attestation`. The pre-freeze claim/confidence sketch stays in `historical/docs/MCP_CONTRACT.md`.

## 0.1.0-docs — 2026-09-22

Documentation alignment only. Protocol number and goldens unchanged.

- `docs/MCP_CONTRACT.md` is a pointer. The MCP sketch is `historical/docs/MCP_CONTRACT.md` and is not shipped.
- README, `docs/PLATFORMS.md`, `docs/PROTOCOL_v0.1.md`, implementer README, historical README, and the v0.1.0 PDF agree on that split.
- Live Graphiti / Mem0 mappings documented in `docs/implementer/LIVE_ADAPTERS.md`.

## 0.1.0-prefreeze — 2026-09-22

Not a protocol-number bump. Tightens `reference-v1` before any public freeze.

- Trusted-origin allowlist: only `tool|document|human|api|vendor|sensor` may raise `HUMAN`/`EXTERNAL`. `episode` and other unknown origins are untrusted.
- `DEGRADED` blocks `ACCEPTED`.
- Scope caps a check only when it names a different entity in the same family (`server01` vs `server02`).
- Timestamps compared as instants (`Z` vs `+00:00`).
- SQLite lineage edges filtered to the requested proposition.
- `may_act`: high-risk + not `ACCEPTED` is `DENY`; any `OPEN` is `REQUIRE_CONFIRMATION` for lower risk.
- Golden comparison ignores `strength`.
- `SESSION_HANDOFF.json` moved to `historical/SESSION_HANDOFF.json`.
- `docs/implementer/third_eval.py` matches all 42 implementer expected axis files without importing `protocol.*`.

## 0.1.0-republish — 2026-09-22

Corrects evaluator holes found on first publish. Protocol number stays `EWP-0.1.0`. Policy identity is now consistently `reference-v1`.

- Check `result` is evaluated: `opposes` opens conflict and blocks `ACCEPTED`; `inconclusive` cannot raise `EXTERNAL`/`HUMAN`.
- Endogenous origin caps `human_attestation` / `human_review` at `INDIRECT`.
- Supporting + opposing polarity implies `conflict=OPEN` even without a `Conflict` row.
- Currency freshness uses checks that confer the chosen verification class.
- Independent lineage counts assertions, evidence, and checks.
- Lock now hashes the evaluator, not only fixtures and goldens.
- Pre-freeze warrantmem ledger/MCP/Postgres sketches moved to `historical/`.
- `tests/test_conformance.py` (`test_3_compression_monotonicity`) uses verification rank, not string comparison.

Goldens regenerated after the policy-identity and evaluator corrections.

## 0.1.0-note — 2026-09-22

Design/conformance note only. Protocol number unchanged.

- `docs/DESIGN_NOTE.md`: normative boundary vs `reference-v1` vs non-normative `strength`.
- Verification class no longer trusts method name alone when `origin_type` is endogenous (verification laundering).
- New pack `protocol/laundering.py` + two-evaluator axis comparison. Frozen 26 goldens unchanged.


## 0.1.0 — 2026-09-21

First frozen release of the **Epistemic Warrant Protocol (EWP)**.

Public name is EWP, not “Warrant Protocol,” to avoid collision with action-authorization systems that already use *warrant* for permission to act.

- Protocol 0.1 / policy `reference-v1`
- Canonical fixtures: 14
- Pathological fixtures: 12
- Golden WarrantViews: 26
- Reference adapters: SQLite PASS, JSON PASS
- Semantic adapter: Fake Graphiti PASS (epistemic isolation)
- Live `graphiti-core 0.30.2`: NOT VALIDATED
- Lock hashes in `RELEASE.lock.json`
- Rule: stores adapt to the protocol. Graphiti adapts to v0.1. v0.1 does not adapt to Graphiti.
- License: MIT (`LICENSE`, `CONTRIBUTING.md`, `SECURITY.md`).

A new store may reveal an adapter bug or a missing test. It does not redefine warrant.
