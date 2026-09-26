# Changelog

## EWP-0.2.1

Protocol `EWP-0.2.0` and policy `reference-v2` are unchanged. No evaluator, fixture, golden, or lock hash changed, and no tool changed behavior.

### MCP tool definitions

- Every tool parameter now has a description, including the nested `check`, `evidence`, `source`, `action`, and `risk_policy` fields: formats, defaults, closed enums, trusted and endogenous `origin_type` values, and verification methods.
- Tool descriptions say what each tool returns, when to use it instead of its nearest sibling, and what it refuses.
- Every tool carries MCP annotations (`title`, `readOnlyHint`, `destructiveHint`, `idempotentHint`, `openWorldHint`). Only the three write tools are not read-only; none is destructive or open-world.
- `ewp_evidence_record` declares `assertion_id`, `asserted_by`, and `assertion_confidence`, which it already accepted.
- `tests/test_mcp.py` fails if a parameter loses its description or a tool its annotations.

### Docs

- `historical/README.md` and `historical/docs/MCP_CONTRACT.md` named the shipped server `python3 -m protocol.mcp_server`; it is `python3 -m ewp.mcp_server`.

## EWP-0.2.0

Protocol `EWP-0.2.0`, policy `reference-v2`. The development iterations previously listed as 0.2.0, 0.2.0-docs, 0.2.1, and 0.2.2 are folded into this entry; none of them was a release. The 26 golden axes are unchanged from 0.1.0 (only their identity fields changed); the hardening pack grew to 26 fixtures, a 35-view invalid pack was added, and all of it is locked.

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
- JSON store writes are serialized per proposition with an OS file lock (released by the OS if a writer dies), and `latest.json` is replaced atomically. Two concurrent writers used to both pass the identity check, and one `view_id` vanished from the history; readers could also hit a half-written `latest.json`. On Windows a replace fails while any process has the file open (another EWP reader, a virus scanner), and an open can fail mid-replace; reads and replaces now retry that sharing conflict briefly instead of failing (4 readers against 4 writers failed about 60 times per run). Snapshot files are written atomically too, and a snapshot is committed once its `view_id` is in the history: only committed snapshots are immutable. A file whose `view_id` is not in the history is an orphan of an interrupted write (partial, identical, or corrected), and a retry replaces it after the same cross-snapshot record-id check as any other commit. A partial file used to make every retry fail with `JSONDecodeError`, and a complete one made the retry a no-op that left the snapshot out of the history. An explicit read returns only committed snapshots; a damaged committed file is an error.
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
- `ewp-ingest` reports an unusable ledger (older schema) with a message instead of a traceback. A bad `--evaluated-at` is refused before the ledger is opened (it used to store every view and then exit 1 with "3 view(s) not stored").
- Record ids are stable across a proposition's snapshots in every store: the JSON store and Mem0 now refuse a later snapshot that reuses an assertion/evidence/check/source id for different content or changes a conflict's participants, as SQLite's ledger already did (one shared check, `codec.record_identity_conflicts`). SQLite stores check subjects sorted, so reordered subjects are not a change. A cross-store test runs one sequence of writes against all three.
- The JSON codec normalizes optional source ids (`extractor_id`, `parent_source_id`) with `str()` like required ones (a number came back from SQLite as text, so an identical re-put was refused).
- Mem0 keeps each record's own `proposition_id` (a variant `pid:<suffix>` was overwritten with the view's, and a later snapshot with the same record was then falsely refused). Graphiti lists the collapse as a named, warrant-neutral field loss.
- `ewp-ingest` and the MCP server report SQLite errors (busy, locked, corrupt) as `EWP_REFUSE_LEDGER_UNAVAILABLE` / a per-view failure instead of a traceback or generic `-32000`.
- The JSON codec reads lineage endpoints from `from_id` / `to_id` only (undocumented `from` / `to` aliases were accepted by the codec but not by the third evaluator).
- Mem0: memories tagged with a `view_id` but no sidecar (an interrupted ingest) are never read, including when the proposition has no completed snapshot yet.
- Mem0 reads follow the mem0ai 2.x client contract: entity ids in `filters`, never top-level (both current clients reject top-level `user_id` on reads, so the adapter's reads failed against them; the test fake accepted the old call). OSS `get_all` is bounded by `top_k` (default 20) and does not page: the adapter asks for `read_limit` and refuses a read at the limit; the hosted client's pages are all read and checked against `count`. The test fakes now follow both 2.x signatures, and `tests/test_mem0_client.py` runs the adapter against a real OSS `mem0.Memory` (mem0ai 2.2.0, offline); CI installs it.
- Live adapters never turn a missing store time into the epoch: a Graphiti episode or a Mem0 memory with no time yields records that are unavailable at every T (they read as 1970, available at every T). A Mem0 per-check memory (`kind: ewp_check`, written outside EWP ingest) with an empty `observed_at` stays unavailable instead of taking the memory's ingest time.
- Mem0 `add` is called once per memory (a retry on `TypeError` could write a memory twice under one ingest, and that snapshot would never match its digest). A memory's `assertion_confidence` is not coerced with `float()`.
- Mem0 snapshot reads are checked against the digest committed in the sidecar. A read that lost one opposing memory used to return the rest as `retrieval_scope=complete` (`TENTATIVE`/`OPEN` became `ACCEPTED`/`NONE`); it now fails. Memories written outside EWP, which have no digest, read as `mem0.unverified` (`DEGRADED`); a sidecar without a digest, or without a positive integer sequence number, is refused (a missing `seq` used to read as 0 and let latest pick an older snapshot). Every memory carries its ingest's sequence number, and a latest read that finds records of a newer uncommitted ingest fails instead of serving the older snapshot as current (a read that lost the newest sidecar used to return the previous snapshot as complete). Two snapshots committed concurrently with the same sequence number have no latest (a random tie-break used to pick one, possibly the older, as complete). A store that hides a whole newer snapshot cannot be detected; the docs say so.
- Graphiti: only edges of the adapter's `group_id` are read, even when a client's search or listing returns others (a search that ignored `group_ids` put another user's fact in the view). An edge that does not state its group is not trusted to be in it. Episodes that state another group are not read either, so another group's parked checks or provenance cannot enter the view. The parked sidecar's `degraded`, `freshness_policy_seconds`, and `omitted_sources` are carried as written and refused when mistyped (a `"true"` string used to read as not degraded, and `int(True)` as a 1-second freshness).
- Graphiti: records are selected by the `proposition_id` their episodes declare, not by group, one episode at a time, so an edge Graphiti merged from episodes of two propositions appears in each view with its own episodes (an all-episodes rule dropped such an edge from both views while both claimed to be complete). With the documented `group_id="user-42"`, `proposition_id="P1"` arrangement the live adapter used to return an empty view marked complete. The `fact_text` fallback is `DEGRADED` (`graphiti.fact_text`) and never joins an edge declared for another proposition.
- Graphiti: a record's time is its own, carried on its episode (see below); when an episode declares none, the record takes the episode's reference time, which an edge's `reference_time` can make later but never earlier, and the edge's `valid_at` (when the fact held in the world) never counts. An episode observed on September 24 with `valid_at` September 20 used to count as evidence at a September 21 evaluation. An episode that cannot be loaded is never turned into a record (its role, polarity, and time are unknown; it used to become supporting evidence dated 1970, and later the edge's ingest time); it is listed in `omitted_sources` of both raw and search views (including when search adds edges the group listing lacked), so the view is `DEGRADED`. The parked `omitted_sources` is merged with what the read could not load, not replaced by it. Record times travel on the episode (`asserted_at` / `observed_at`, one per role), so a record's own time comes back exactly: the fake ingest stamped every assertion edge with the first assertion's time, and a record whose own time was empty took its episode's, becoming available where the kernel reads it as unavailable. A source whose records of one kind carry different times is refused at ingest. Live Graphiti never replaces an episode, so each re-ingest adds a parked sidecar: the newest by Graphiti's `created_at` applies (listing order used to decide, so an older sidecar could drop a newer open conflict), and two different sidecars created at the same instant fail the read.
- Graphiti live ingest writes one episode per source declaring every role it plays and its evidence polarity, and reads take role and polarity from the episode. An opposing-evidence episode on an extracted edge used to come back as `supports`, and a source that was both assertion and evidence lost its evidence polarity. A source with both supporting and opposing evidence is refused at ingest. An episode that cannot be loaded degrades every view of its group, in a shared group or one named for the proposition, instead of being dropped or read as support.
- Record arrays (`assertions`, `evidence`, `checks`, `conflicts`, `lineage`) that are present but not lists are refused by the codec and the third evaluator; `"checks": false`, `"evidence": ""`, `"conflicts": 0`, and `"lineage": {}` used to read as empty. `adapter_meta` must be an object, `assertion_confidence` must be a JSON number that a float can hold (`"0.99"` and `true` used to be converted by `float()`, and an integer beyond float range crashed the codec with `OverflowError` while the third evaluator accepted it), the view's `proposition_id` must not be empty, and `view_id` must be an id (`{}` or `false` used to be replaced by a derived id). Both reference evaluators refuse the same shapes from Python callers (`checks=""` or `lineage={}` used to evaluate as empty), and check every `SCHEMA.md` required field on the view itself (a view whose sources all had `content_hash=None` evaluated to `ACCEPTED`). Seven new invalid views.
- SQLite and JSON `get_view` no longer take `omitted_sources` / `retrieval_scope` / `degraded` / `freshness_policy_seconds` overrides, which returned changed metadata under the stored `view_id`. Two test helpers relied on them, masking any loss of that metadata in the canonical runner.
- Mem0 retry after an interrupted ingest: every memory carries the ingest's `ingest_id`, and a snapshot is the memories of the ingest its sidecar committed. A retry used to read the crashed attempt's records too and was refused for duplicate ids. Two racing commits of different content under one `view_id` are refused on read instead of producing a mixed view.

### MCP façade

- Stdio uses the MCP stdio transport: newline-delimited JSON-RPC, one message per line. (A development iteration shipped Content-Length framing, which no MCP client speaks.) Protocol revisions `2025-06-18`, `2025-03-26`, and `2024-11-05` are negotiated. Notifications are never answered.
- Every write needs the server-side ingest role (`--allow-ingest` on stdio, the token on HTTP), including conflict, lineage, and view-metadata writes. Without it the server is evaluate-only. Previously an anonymous caller could resolve an open conflict, clear `degraded`, or stretch freshness and turn a stale, degraded view into `ACCEPTED`. Trusted origins also need `ingest_attestation=true`.
- Inline views are hypothetical. `ewp_warrant_now` demotes their trusted origins to `inline:<origin>` unless the caller holds the ingest role and attests; `ewp_may_act` refuses them. Previously any caller could send a made-up view and get `MAY_ACT` on a high-risk, irreversible action.
- `ewp_may_act` decides on the latest stored snapshot at the server clock. A supplied `evaluated_at` is only a sanity check (refused beyond 300 s) and never the decision time; a supplied `view_id` must be the latest (`EWP_REFUSE_STALE_VIEW_FOR_ACTION`). A caller could previously pick an older snapshot, or a time up to 300 s earlier, that lacked a recent opposing check and turned `DENY` into `MAY_ACT`. It requires `action.risk` in `low|medium|high` and a boolean `action.reversible` (a missing risk used to default to `low`; `"false"` used to read as reversible), and accepts `risk_policy` only from a caller with the ingest role, honoring its flags.
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
- A request with `"id": null` gets a `-32600` reply instead of silence; so does an id that is not a string or integer (it used to be echoed back). Non-object `params`, and a non-string `name`, `uri`, or `protocolVersion`, get `-32602` (they returned a generic `-32000` with a Python error). HTTP answers `405` for methods other than GET and POST. Resource URIs decode like URIs: proposition ids are percent-decoded path segments (an id with `/` or a space was unreadable), the query keeps `+` (an `evaluated_at` with `+00:00` became a space and failed), and a proposition named `warrant` is readable. `tests/test_transport_fuzz.py` sends 500 malformed JSON-RPC and HTTP requests and requires a specific error for each and a server that keeps answering. `resources/templates/list` lists the proposition resources.
- The opposing-check warning names the class of the check that opposes (it used to name the strongest class, which can come from a different, supporting check).
- `ingest_attestation` counts only when it is JSON `true`; `"false"`, `1`, `[]`, and `{}` were read as attesting. A `view` argument that is present but not an object is refused (`false` used to read as no inline view). Incremental writes normalize `extractor_id` / `parent_source_id` to strings like full views. Tool arguments are checked: a `null` id is missing (it used to become `"None"`), `check` / `evidence` / `action` / `source` / `risk_policy` must be objects, `new_view_id` must be an id (`5` used to be stored as a number), incremental `assertion_confidence` must be a JSON number (`true` and `"0.99"` were converted by `float()`), and incremental source fields that are present are kept, not replaced with defaults (an empty `lineage_id` used to become a separate lineage, while a full view kept it).

### Conformance and release

- Hardening pack (`ewp/laundering.py`) adds subject-binding cases (`customer-42`/`invoice-999`, `server01`/`customer-42`, omitted check subjects, a shared subject that verifies), an unparsable check time, and an unrelated `superseded_by` edge (26 fixtures with the two below).
- `tests/test_adapter_roundtrip.py` runs all 52 fixtures through SQLite, JSON, fake Graphiti, and Mem0 and requires identical normative axes. It found the Mem0 polarity and timestamp losses above.
- `RELEASE.lock.json` hashes fixtures (now including the hardening pack), evaluator (now including `versions.py`), the policy text (`POLICY.md`, `policy.json`), goldens, and the implementer pack. Hashes are over LF-normalized content; `.gitattributes` keeps checkouts LF.
- `tests/report.py` prints `CONFORMANT` only for a CI stamp whose hashes match the current tree; a stale stamp reports `CLAIM_ONLY`.
- `docs/implementer/third_eval.py` implements `reference-v2` from `POLICY.md` / `policy.json` only and matches all 52 expected files. `tests/test_goldens.py` checks the reference evaluator against the same 52.
- `tests/test_mcp.py` drives the real server over stdio as a subprocess and, when the `mcp` package is installed, through the official MCP Python SDK client (verified against `mcp` 2.2.0, negotiating `2025-06-18`). The GitHub workflow installs `mcp` so this runs in CI.
- Removed `protocol/pathological_fixtures.py`, which was not valid Python and was not imported.
- `tests/test_adapter_roundtrip.py` also compares every `SCHEMA.md` field: the codec, SQLite, JSON, and Mem0 must return views unchanged; fake Graphiti may lose only the fields listed in `GRAPHITI_FIELD_LOSSES`.
- Hardening fixtures `zero_freshness_is_stale` and `variant_record_propositions`; invalid pack of 35 views (one per input rule) in `docs/implementer/invalid/`, refused by the kernel, the codec, and the third evaluator.
- The CI stamp carries `ci_surface_sha256` over every file CI exercises (kernel, adapters, MCP, tests, implementer pack, examples, workflow), hashed before the run; `tests/report.py` requires it to match. Report counts come from the packs.
- Differential fuzz tests: `tests/test_parity_fuzz.py` replaces every field of every implementer fixture with malformed values (about 88,000 views) and requires the kernel, the second evaluator, and the third evaluator to refuse together or agree, never crash; `tests/test_mcp_fuzz.py` requires every malformed MCP tool argument to succeed or be refused with an `EWP_*` code. They found: the kernel crashed on a list-valued enum field and both evaluators on a non-string `evaluated_at`; the third evaluator crashed on a non-string `proposition_id` and did not check `view_id`; the codec converted non-string lineage endpoints and `proposition_id` with `str()`; and `ewp_evidence_record` returned a generic `-32000` for an out-of-range confidence. A store-neutrality fuzz (`tests/test_store_fuzz.py`) round-trips every accepted malformed view through SQLite, JSON, and Mem0: Mem0 replaced empty strings it had written with defaults on read (the digest check then refused the snapshot), and SQLite could not store a `freshness_policy_seconds` beyond 64 bits. Mem0 now fills in defaults only for missing values, and `freshness_policy_seconds` is capped at `2^53 - 1`, the largest integer every JSON implementation represents exactly. All fixed; four invalid views added (35). `ewp_memory_context` refuses a non-string `evaluated_at` (a falsy one used to mean "now") and `ewp_evidence_record` a non-string `text`.
- The GitHub workflow uses `actions/checkout@v7` and `actions/setup-python@v7`, which run on Node.js 24 (v4 and v5 targeted the deprecated Node.js 20).
- CI runs `runner_pathological.py` and `test_ingest_cli.py`, and a tester-path job: `pip install .`, `ewp-ingest` on the example, and an `ewp-mcp` handshake.
- `pyproject.toml` declares the license as an SPDX expression (`license = "MIT"`, `license-files`) with `setuptools>=77`; the table form is deprecated, and setuptools will stop building it after 2027-02-18.
- The README lock block and the PDF read pack counts from the packs themselves (the README showed `Invalid refused: 24/24` after the pack grew).
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
- `POLICY.md` and `PROTOCOL.md`: `EXTERNAL` / `HUMAN` classify the verification channel, not source quality. `SCHEMA.md`: record arrays default to `[]`; `view_id` is part of interchange, and deriving it from content is a reference-ingest convenience.
- `docs/PLATFORMS.md`: build complete views by key, not similarity; extracting nothing is a valid ingest result; an `origin_locator` convention for pointing at exact passages.
- `docs/OPEN_QUESTIONS.md`: retraction without replacement (unresolved, with what each current encoding yields), assertion polarity, validity time, separate capabilities for ingest and action policy.
- README, QUICKSTART, and the PDF name the version as EWP-0.2.0 only.
- README, CONTRIBUTING, CONFORMANCE, SCHEMA, `MCP_CONTRACT.md`, `LIVE_ADAPTERS.md`, and the PDF describe the real Mem0 client test, the fuzz tests, concurrent-safe stores, resource URI encoding, and the Graphiti episode rules. `tests/report.py` wording says "exact CI surface". The example data notes that its `ACCEPTED` row turns `STALE` after 2027-09-20.

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
