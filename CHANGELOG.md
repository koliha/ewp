# Changelog

## [Unreleased] — EWP-0.2.0

Not yet released. Protocol `EWP-0.2.0`, policy `reference-v2`. The development iterations previously listed as 0.2.0, 0.2.0-docs, 0.2.1, and 0.2.2 are folded into this entry; none of them was a release. The 26 golden axes are unchanged from 0.1.0 (only their identity fields changed); the hardening pack grew to 24 fixtures and all 50 fixtures are locked.

### Identity

- Policy is `reference-v2`. Subject binding, supersession scope, availability, and input validation changed, so `reference-v1` no longer names this evaluator's judgments. `warrant_now` refuses `reference-v1` and any other identity it does not implement.
- `WarrantView` carries `protocol_version` (`EWP-0.2.0`). Reproducibility is stated over protocol version + view + policy + `evaluated_at`.
- `WarrantView.normative()` is `protocol_version`, `proposition_id`, `view_id`, `policy_id`, `policy_version`, `evaluated_at`, and the five axes. `rationale_codes` and `strength` are diagnostic, not part of the equality contract. `docs/PROTOCOL.md`, `docs/implementer/SCHEMA.md`, and the code now agree on this.

### Evaluator (`reference-v2`)

- Subject binding uses declared `subjects[]` as exact ids. `scope` is never scraped. There is no family inference: a check about `invoice-999` or `printer-7` no longer verifies a `customer-42` or `server01` proposition. A check that omits subjects cannot verify a view that declares them.
- A `superseded_by` edge supersedes the proposition only if its `from_id` is the `proposition_id` or a variant `proposition_id:<suffix>`. Unrelated edges in the bounded view no longer mark it `SUPERSEDED`.
- Records whose instant is after `evaluated_at`, missing, or unparsable are not available at T. This covers assertions, evidence, and checks. Naive timestamps are UTC; instants are compared, not strings.
- Selecting `freshest_check` no longer crashes on an unparsable timestamp; it considers only checks available at T.
- Closed enums fail closed: `polarity`, `result`, conflict `status`, and lineage `kind` outside their enums make the view invalid (`InvalidEvidenceView`). Previously `result: "pending"` verified like `supports`, `status: "Open"` read as no conflict, and `polarity: "oppose"` was silently dropped.
- Origin trust: only `tool|document|human|api|vendor|sensor` may raise `EXTERNAL`/`HUMAN`; endogenous and unknown origins cap at `INDIRECT`. `result=opposes` opens conflict and blocks `ACCEPTED`; `result=inconclusive` cannot raise the class.

### Action gate

- `may_act` returns `DENY` for a `SUPERSEDED` proposition at high risk and at least `REQUIRE_CONFIRMATION` otherwise (low risk used to return `MAY_ACT`).
- `may_act` refuses an unknown risk level instead of treating it as medium.
- `high_requires_no_open_conflict` and `reversible` are live.

### Store and adapters

- SQLite partitions every record by `proposition_id`. View metadata is one row per proposition, read by exact key. Previously two propositions sharing a `view_id` (e.g. `mcp`), or sharing record ids like `a1`/`k1`/`s1`, could overwrite each other's completeness, subjects, freshness, or records.
- SQLite is append-only for sources, assertions, evidence, and checks: rewriting an existing id with different content raises `ImmutableRecordError`. Conflict participants are fixed; status and note may change. Writes are transactional. Databases from earlier development schemas are refused with a clear message.
- SQLite persists view completeness (`omitted_sources`, `retrieval_scope`, `degraded`, freshness, subjects).
- Mem0 and Graphiti (fake ingest and live client) park and restore the view's `subjects[]` and each check's `subjects[]`. A Mem0 round trip used to turn a `customer-42`/`customer-99` mismatch into `EXTERNAL`/`ACCEPTED`.
- Mem0 ingest writes each assertion and each evidence item as its own memory with its own polarity and original timestamp. Previously it kept one memory per source, forced `polarity=supports`, and used Mem0's `created_at` (ingest time) as observation time, which dropped opposition and could make evidence look future-dated.
- Graphiti ingest emits an edge for evidence whose text is not already an assertion, so opposing evidence-only lineages survive `raw_view`. Edges may carry `polarity=opposes`. Parked sidecars need a matching `proposition_id` and are found by kind/content/name, not by Graphiti's assigned UUID.
- Mem0 memories without `metadata.ewp.proposition_id` do not enter a proposition view.

### MCP façade

- Stdio uses the MCP stdio transport: newline-delimited JSON-RPC, one message per line. (A development iteration shipped Content-Length framing, which no MCP client speaks.) Protocol revisions `2025-06-18`, `2025-03-26`, and `2024-11-05` are negotiated. Notifications are never answered.
- Every write needs the server-side ingest role (`--allow-ingest` on stdio, the token on HTTP), including conflict, lineage, and view-metadata writes. Without it the server is evaluate-only. Previously an anonymous caller could resolve an open conflict, clear `degraded`, or stretch freshness and turn a stale, degraded view into `ACCEPTED`. Trusted origins also need `ingest_attestation=true`.
- Inline views are hypothetical. `ewp_warrant_now` demotes their trusted origins to `inline:<origin>` unless the caller holds the ingest role and attests; `ewp_may_act` refuses them. Previously any caller could send a made-up view and get `MAY_ACT` on a high-risk, irreversible action.
- `ewp_may_act` evaluates stored evidence at server time (supplied `evaluated_at` must be within 300 s), requires `action.risk` in `low|medium|high` and a boolean `action.reversible` (a missing risk used to default to `low`; `"false"` used to read as reversible), and accepts `risk_policy` only from a caller with the ingest role, honoring its flags.
- `ewp_memory_context` defaults `evaluated_at` to server time. `ewp_may_act` refuses a caller-built `WarrantView`. Incremental records must supply `content_hash` and `observed_at`.
- HTTP: `--allow-ingest` is refused with `--http` (it would grant every caller the ingest role). The token comes from `EWP_INGEST_TOKEN` or `--ingest-token-file`, not argv, and is compared in constant time. Bodies over 1 MiB get `413` from headers alone. Notifications get `202`. HTTP remains plain JSON-RPC, not MCP Streamable HTTP.
- The pre-freeze claim/confidence sketch stays in `historical/docs/MCP_CONTRACT.md`.

### Conformance and release

- Hardening pack (`protocol/laundering.py`) adds subject-binding cases (`customer-42`/`invoice-999`, `server01`/`customer-42`, omitted check subjects, a shared subject that verifies), an unparsable check time, and an unrelated `superseded_by` edge: 24 fixtures.
- `tests/test_adapter_roundtrip.py` runs all 50 fixtures through SQLite, JSON, fake Graphiti, and Mem0 and requires identical normative axes. It found the Mem0 polarity and timestamp losses above.
- `RELEASE.lock.json` hashes fixtures (now including the hardening pack), evaluator (now including `versions.py`), the policy text (`POLICY.md`, `policy.json`), goldens, and the implementer pack. Hashes are over LF-normalized content; `.gitattributes` keeps checkouts LF.
- `tests/report.py` prints `CONFORMANT` only for a CI stamp whose hashes match the current tree; a stale stamp reports `CLAIM_ONLY`.
- `docs/implementer/third_eval.py` implements `reference-v2` from `POLICY.md` / `policy.json` only and matches all 50 expected files. `tests/test_goldens.py` checks the reference evaluator against the same 50.
- `tests/test_mcp.py` drives the real server over stdio as a subprocess and, when the `mcp` package is installed, through the official MCP Python SDK client (verified against `mcp` 2.2.0, negotiating `2025-06-18`). The GitHub workflow installs `mcp` so this runs in CI.
- Removed `protocol/pathological_fixtures.py`, which was not valid Python and was not imported.

### Documentation

- `docs/PROTOCOL_v0.1.md` is now `docs/PROTOCOL.md` and states the 0.2.0 contract.
- `docs/EWP_v0.2.0.pdf` is rebuilt; `docs/build_guide_pdf.py` reads identity and hashes from `RELEASE.lock.json` so the guide cannot drift from the lock.
- README, CONFORMANCE, CONTRIBUTING, SECURITY, VERSION, `docs/MCP_CONTRACT.md`, `docs/PLATFORMS.md`, `docs/DESIGN_NOTE.md`, and the implementer pack describe `reference-v2`, the ingest role, stdio framing, and the lock.
- Security: origin metadata is assumed established at the ingestion/adapter boundary. EWP does not authenticate evidence entering the ledger.

### Known limits

- Conflict rows and lineage edges carry no timestamp, so they are not filtered by availability at T: an edge recorded later still applies when replaying an earlier T.
- Live `graphiti-core 0.30.2` is not validated.
- HTTP is not MCP Streamable HTTP.

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
