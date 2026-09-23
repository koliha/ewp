# Changelog

## EWP-0.2.0

Protocol `EWP-0.2.0`, policy `reference-v2`. The development iterations previously listed as 0.2.0, 0.2.0-docs, 0.2.1, and 0.2.2 are folded into this entry; none of them was a release. The 26 golden axes are unchanged from 0.1.0 (only their identity fields changed); the hardening pack grew to 26 fixtures, a 24-view invalid pack was added, and all of it is locked.

### Identity

- The Python package is `ewp` (was `protocol`, a generic top-level name that could collide in a tester's environment): `from ewp.warrant import warrant_now`, `python -m ewp.mcp_server`. The `ewp-mcp` and `ewp-ingest` commands are unchanged.
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
- Views are bounded: an assertion or evidence item about another proposition, or a conflict row that does not name the proposition, makes the view invalid. Previously a `P-win` view whose records were all about another proposition evaluated to `ACCEPTED`.
- Field types are enforced: `subjects` must be lists of strings (a bare string was iterated as characters, so `customer-99` could verify `customer-42` on shared letters); `freshness_policy_seconds` must be a non-negative int, not bool; `degraded` a bool; `retrieval_scope` a string.
- Checks whose subjects do not bind still count toward implied conflict (stated explicitly in `POLICY.md`).
- Identity is unambiguous: repeated assertion/evidence/check/conflict ids in one view are refused (even identical repeats), and one `source_id` must carry one `SourceRef`. Previously one source with two `lineage_id`s counted as two independent lineages in memory while SQLite refused the same view.
- `omitted_sources` and conflict `proposition_ids` must be lists of strings (a string was iterated as characters); lineage endpoints must be non-empty strings (a missing endpoint was stored as `"None"`).
- A missing or null required field, a record that is not an object, or a non-numeric or non-finite (`nan`, `inf`) confidence is refused as an invalid view with a clear message (the codec used to raise a bare `KeyError`/`TypeError`, and turned a null id into the string `"None"`); the third evaluator checks the same required fields.
- An unparsable `evaluated_at` is refused with a clear message by both reference evaluators and the third evaluator (the third evaluator used to return `UNACCEPTED`).

### Action gate

- `may_act` returns `DENY` for a `SUPERSEDED` proposition at high risk and at least `REQUIRE_CONFIRMATION` otherwise (low risk used to return `MAY_ACT`).
- `may_act` refuses an unknown risk level instead of treating it as medium.
- `high_requires_no_open_conflict` and `reversible` are live.

### Store and adapters

- SQLite partitions every record by `proposition_id`. Previously two propositions sharing a `view_id` (e.g. `mcp`), or sharing record ids like `a1`/`k1`/`s1`, could overwrite each other's completeness, subjects, freshness, or records.
- SQLite is append-only for sources, assertions, evidence, and checks: rewriting an existing id with different content raises `ImmutableRecordError`. Conflict participants are fixed across views; status and note belong to each snapshot. Writes are transactional. Databases from earlier development schemas are refused with a clear message.
- SQLite persists view completeness (`omitted_sources`, `retrieval_scope`, `degraded`, freshness, subjects).
- Mem0 and Graphiti (fake ingest and live client) park and restore the view's `subjects[]` and each check's `subjects[]`. A Mem0 round trip used to turn a `customer-42`/`customer-99` mismatch into `EXTERNAL`/`ACCEPTED`.
- Mem0 ingest writes each assertion and each evidence item as its own memory with its own polarity and original timestamp. Previously it kept one memory per source, forced `polarity=supports`, and used Mem0's `created_at` (ingest time) as observation time, which dropped opposition and could make evidence look future-dated.
- Graphiti ingest emits an edge for evidence whose text is not already an assertion, so opposing evidence-only lineages survive `raw_view`. Edges may carry `polarity=opposes`. Parked sidecars need a matching `proposition_id` and are found by kind/content/name, not by Graphiti's assigned UUID.
- Mem0 memories without `metadata.ewp.proposition_id` do not enter a proposition view.
- The JSON codec keeps falsy values: `freshness_policy_seconds: 0` used to become 30 days and an empty `retrieval_scope` used to read as `complete`. A missing `view_id` is derived from the content.
- SQLite views are immutable `(proposition_id, view_id)` snapshots with explicit membership over the append-only ledger. `get_view(pid, id)` returns exactly that snapshot; `get_view(pid)` the latest; `extend_view` appends atomically. Previously a second view for a proposition replaced the first's metadata and merged its evidence under the old `view_id`. Unknown propositions raise `MissingViewError`. Older development databases are refused. `SQLiteAdapter` closes as a context manager.
- JSON store: files are named by hashes of the ids (a proposition id could previously escape the store root, and `a/b` collided with `a_b`), writes and reads are validated (a `status: "Open"` conflict used to be stored as resolved), and views are immutable snapshots like SQLite.
- Mem0 keeps every `SourceRef` field (`source_id`, `observed_at`, `extractor_id`), `assertion_confidence: 0`, and the `view_id`.
- Graphiti edges carry `roles`, so an evidence-only record no longer comes back as an assertion (which could lift `UNACCEPTED` to `TENTATIVE`) and an assertion-only record no longer gains supporting evidence. Ingest stores `snapshot_id`/`extractor_id`; parked `subjects` and `view_id` are decoded safely.
- Live Graphiti (**experimental**): `search_view` applies the parked sidecar (it used to drop checks, conflicts, lineage, subjects, and freshness); ingest writes evidence-only sources and sets `reference_time` from the source's `observed_at`.
- New `ewp-ingest` command loads EvidenceViews from JSON into a ledger; trusted origins require `--attest-trusted-origins`.
- All ids are proposition-local, including `conflict_id` (it was ledger-global in SQLite, so unrelated propositions could not both use `c1`). Schema version 4.
- One canonical, record-order-independent form of a view (`codec.canonical_dict`) drives content-derived ids, SQLite and JSON snapshot comparison, and adapter conformance. Reordered but identical snapshots were refused as mutations and got different ids.
- SQLite writes run in `BEGIN IMMEDIATE` transactions, so `extend_view` is atomic across processes sharing a ledger: concurrent appends from separate processes used to drop records from the latest snapshot. `SQLiteAdapter(path, read_only=True)` opens an existing ledger read-only and refuses a missing path.
- Mem0 implements immutable snapshots: every memory is tagged with its `view_id`, the sidecar (written last) carries a digest and sequence, `raw_view(pid, id)` returns exactly that snapshot, identical re-ingest is a no-op, and changed content under an existing id is refused. `raw_view("P", "v1")` used to return every record ever written for `P`, with duplicates.
- The docs state that the Graphiti mappings keep one current view per proposition and are not snapshot stores.
- Graphiti sources take their `observed_at` from the episode, not from whichever edge cites it, so one episode behind two facts is one consistent `SourceRef`.
- `ewp-ingest` reports an unusable ledger (older schema) with a message instead of a traceback.
- Record ids are stable across a proposition's snapshots in every store: the JSON store and Mem0 now refuse a later snapshot that reuses an assertion/evidence/check/source id for different content or changes a conflict's participants, as SQLite's ledger already did (one shared check, `codec.record_identity_conflicts`). SQLite stores check subjects sorted, so reordered subjects are not a change. A cross-store test runs one sequence of writes against all three.
- The JSON codec normalizes optional source ids (`extractor_id`, `parent_source_id`) with `str()` like required ones (a number came back from SQLite as text, so an identical re-put was refused).
- Mem0 keeps each record's own `proposition_id` (a variant `pid:<suffix>` was overwritten with the view's, and a later snapshot with the same record was then falsely refused). Graphiti lists the collapse as a named, warrant-neutral field loss.
- `ewp-ingest` and the MCP server report SQLite errors (busy, locked, corrupt) as `EWP_REFUSE_LEDGER_UNAVAILABLE` / a per-view failure instead of a traceback or generic `-32000`.
- The JSON codec reads lineage endpoints from `from_id` / `to_id` only (undocumented `from` / `to` aliases were accepted by the codec but not by the third evaluator).
- Mem0: memories tagged with a `view_id` but no sidecar (an interrupted ingest) are never read, including when the proposition has no completed snapshot yet.

### MCP façade

- Stdio uses the MCP stdio transport: newline-delimited JSON-RPC, one message per line. (A development iteration shipped Content-Length framing, which no MCP client speaks.) Protocol revisions `2025-06-18`, `2025-03-26`, and `2024-11-05` are negotiated. Notifications are never answered.
- Every write needs the server-side ingest role (`--allow-ingest` on stdio, the token on HTTP), including conflict, lineage, and view-metadata writes. Without it the server is evaluate-only. Previously an anonymous caller could resolve an open conflict, clear `degraded`, or stretch freshness and turn a stale, degraded view into `ACCEPTED`. Trusted origins also need `ingest_attestation=true`.
- Inline views are hypothetical. `ewp_warrant_now` demotes their trusted origins to `inline:<origin>` unless the caller holds the ingest role and attests; `ewp_may_act` refuses them. Previously any caller could send a made-up view and get `MAY_ACT` on a high-risk, irreversible action.
- `ewp_may_act` evaluates stored evidence at server time (supplied `evaluated_at` must be within 300 s), requires `action.risk` in `low|medium|high` and a boolean `action.reversible` (a missing risk used to default to `low`; `"false"` used to read as reversible), and accepts `risk_policy` only from a caller with the ingest role, honoring its flags.
- `ewp_memory_context` defaults `evaluated_at` to server time. `ewp_may_act` refuses a caller-built `WarrantView`. Incremental records must supply `content_hash` and `observed_at`.
- HTTP: `--allow-ingest` is refused with `--http` (it would grant every caller the ingest role). The token comes from `EWP_INGEST_TOKEN` or `--ingest-token-file`, not argv, and is compared in constant time. Bodies over 1 MiB get `413` from headers alone. Notifications get `202`. HTTP remains plain JSON-RPC, not MCP Streamable HTTP.
- The pre-freeze claim/confidence sketch stays in `historical/docs/MCP_CONTRACT.md`.
- `ewp_list_propositions` finds propositions by id or assertion text so an agent can discover what is stored.
- Reads report the stored `view_id` (they used to report `"mcp"`) and accept an optional `view_id`; appends create a new snapshot and return its id (`new_view_id` optional).
- A proposition or `view_id` that was never stored returns `EWP_REFUSE_MISSING_VIEW` instead of silently evaluating an empty view.
- `ewp_evidence_record` requires `polarity`. The ingest role is checked before the payload is examined.
- Error shapes follow MCP: tool argument errors are `isError` results (`EWP_REFUSE_INVALID_ARGUMENTS`), resource errors are JSON-RPC errors (`-32002` for a missing proposition).
- A server that cannot write opens its ledger read-only: `--db` is required, a missing file exits with `ledger not found` instead of creating an empty ledger, and the handle itself cannot write.
- `ewp_memory_context` warns when an `EXTERNAL`/`HUMAN` check opposes the claim, since `verification=EXTERNAL` then means checked and contradicted.
- A request with `"id": null` gets a `-32600` reply instead of silence. `resources/templates/list` lists the proposition resources.
- The opposing-check warning names the class of the check that opposes (it used to name the strongest class, which can come from a different, supporting check).

### Conformance and release

- Hardening pack (`ewp/laundering.py`) adds subject-binding cases (`customer-42`/`invoice-999`, `server01`/`customer-42`, omitted check subjects, a shared subject that verifies), an unparsable check time, and an unrelated `superseded_by` edge (26 fixtures with the two below).
- `tests/test_adapter_roundtrip.py` runs all 52 fixtures through SQLite, JSON, fake Graphiti, and Mem0 and requires identical normative axes. It found the Mem0 polarity and timestamp losses above.
- `RELEASE.lock.json` hashes fixtures (now including the hardening pack), evaluator (now including `versions.py`), the policy text (`POLICY.md`, `policy.json`), goldens, and the implementer pack. Hashes are over LF-normalized content; `.gitattributes` keeps checkouts LF.
- `tests/report.py` prints `CONFORMANT` only for a CI stamp whose hashes match the current tree; a stale stamp reports `CLAIM_ONLY`.
- `docs/implementer/third_eval.py` implements `reference-v2` from `POLICY.md` / `policy.json` only and matches all 52 expected files. `tests/test_goldens.py` checks the reference evaluator against the same 52.
- `tests/test_mcp.py` drives the real server over stdio as a subprocess and, when the `mcp` package is installed, through the official MCP Python SDK client (verified against `mcp` 2.2.0, negotiating `2025-06-18`). The GitHub workflow installs `mcp` so this runs in CI.
- Removed `protocol/pathological_fixtures.py`, which was not valid Python and was not imported.
- `tests/test_adapter_roundtrip.py` also compares every `SCHEMA.md` field: the codec, SQLite, JSON, and Mem0 must return views unchanged; fake Graphiti may lose only the fields listed in `GRAPHITI_FIELD_LOSSES`.
- Hardening fixtures `zero_freshness_is_stale` and `variant_record_propositions`; invalid pack of 24 views (one per input rule) in `docs/implementer/invalid/`, refused by the kernel, the codec, and the third evaluator.
- The CI stamp carries `ci_surface_sha256` over every file CI exercises (kernel, adapters, MCP, tests, implementer pack, examples, workflow), hashed before the run; `tests/report.py` requires it to match. Report counts come from the packs.
- CI runs `runner_pathological.py` and `test_ingest_cli.py`, and a tester-path job: `pip install .`, `ewp-ingest` on the example, and an `ewp-mcp` handshake.
- `RELEASE.lock.json` and the CI stamp are written atomically (temp file + replace, with a short retry), so a Windows scanner briefly holding the file no longer fails `--write-lock`. Unused `SQLiteAdapter.has_proposition` removed.
- Removed `protocol/validate.py` (unused), a dead expression in `runner_graphiti.py`, and a test assertion that could not fail.
- Tests: four OS processes appending concurrently to one ledger; read-only ledger (missing path, tool writes, raw SQL writes); per-proposition conflict ids and order-independent snapshots; Mem0 v1/v2 snapshots, idempotent re-ingest, interrupted ingest; read-only agent server end to end; the opposing-check warning; null ids and resource templates.
- The third evaluator treats a `null` field as its schema default and compares `SourceRef`s field by field, like the kernel (it refused valid views that spelled an optional field as `null` or omitted it). A parity test runs every fixture through both evaluators in those spellings.

### Documentation

- `docs/PROTOCOL_v0.1.md` is now `docs/PROTOCOL.md` and states the 0.2.0 contract.
- `docs/EWP_v0.2.0.pdf` is rebuilt; `docs/build_guide_pdf.py` reads identity and hashes from `RELEASE.lock.json` so the guide cannot drift from the lock.
- README, CONFORMANCE, CONTRIBUTING, SECURITY, VERSION, `docs/MCP_CONTRACT.md`, `docs/PLATFORMS.md`, `docs/DESIGN_NOTE.md`, and the implementer pack describe `reference-v2`, the ingest role, stdio framing, and the lock.
- Security: origin metadata is assumed established at the ingestion/adapter boundary. EWP does not authenticate evidence entering the ledger.
- `QUICKSTART.md` and `examples/quickstart.json`: install, load evidence, connect Claude Code or Claude Desktop, bring your own data.
- `POLICY.md`, `SCHEMA.md`, `PROTOCOL.md`, `MCP_CONTRACT.md`, `CONFORMANCE.md`, and `LIVE_ADAPTERS.md` describe bounded views, typed fields, snapshots, field-level round trips, discovery, and the experimental live Graphiti mapping.
- README, QUICKSTART, and the PDF name the version as EWP-0.2.0 only. `tests/report.py` wording says "exact CI surface". The example data notes that its `ACCEPTED` row turns `STALE` after 2027-09-20.

### Known limits

- Conflict rows and lineage edges carry no timestamp, so they are not filtered by availability at T: an edge recorded later still applies when replaying an earlier T.
- Live `graphiti-core 0.30.2` is not validated.
- HTTP is not MCP Streamable HTTP.
- Assertions carry no polarity: every available assertion counts as grounds for `TENTATIVE`, including one that denies the proposition. Planned for a later policy.

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
