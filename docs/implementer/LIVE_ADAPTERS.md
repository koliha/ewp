# Live Graphiti and Mem0 adapters

EWP-0.2.0 ships fake Graphiti + SQLite + JSON so the kernel can be locked
without Neo4j or a Mem0 key. The Mem0 adapter is the production mapping for
Mem0 and targets the mem0ai 2.x client contract: `tests/test_mem0_client.py`
runs it against a real OSS `mem0.Memory` (mem0ai 2.2.0, offline: mock
embeddings, local Qdrant, `infer=False`). The hosted `MemoryClient` is covered
by a fake that follows its 2.x signatures and paging; it has not been run
against the hosted API. The live Graphiti adapter is **experimental**: it has
not been run against a real `graphiti-core`, whose `add_episode()` LLM
extractor decides which fields survive.
`tests/test_adapter_roundtrip.py` runs every fixture through the fake
Graphiti and Mem0 paths and requires identical axes. Mem0 must also return
every field unchanged; fake Graphiti may lose only the fields listed in
`GRAPHITI_FIELD_LOSSES` (record ids, asserter, confidence, evidence content,
duplicate identical assertions, record-level variant proposition ids).

```
store client  →  EvidenceView  →  warrant_now(view, policy, evaluated_at)
```

Neither adapter is a second epistemology. Graphiti `invalid_at` and Mem0
`score` stay in `adapter_meta` / evidence notes. They never become axes.

## Graphiti (`ewp/graphiti_client_adapter.py`)

```python
from ewp.graphiti_client_adapter import GraphitiClientAdapter
from ewp.types import Policy
from ewp.warrant import warrant_now

adapter = GraphitiClientAdapter(graphiti, group_id="user-42", proposition_id="P-os")
view = await adapter.raw_view("P-os")
print(warrant_now(view, Policy(), "2026-09-22T15:00:00+00:00").warrant)
```

| Graphiti field | EWP field | Notes |
|---|---|---|
| `EntityEdge.fact` | `Assertion.text` / `EvidenceItem.content` | Extractor output. origin defaults to `episode`. |
| `EntityEdge.episodes[]` | `SourceRef.source_id` | One record per episode on the edge, for each role the episode declares (see `kind` below). |
| `EpisodicNode.metadata.lineage_id` or `source_description` JSON | `SourceRef.lineage_id` | Must be written by the caller. Graphiti must not invent it. |
| `valid_at` / `invalid_at` / `expired_at` | evidence note only | Store-local. Not currency, not verification, and never an observation time: `valid_at` is when the fact held in the world. |
| episode `reference_time` (`EpisodicNode.valid_at`) | `observed_at` of the records citing it | When the source was observed. A record is available at T only after this; an edge's own reference time can make it later, never earlier. |
| episode `asserted_at` / `observed_at` (`source_description`) | the time of the assertion and evidence records citing it | Records are one per episode on an edge, so a record's own time travels on its episode, one per role. A source whose assertions (or evidence items) carry different times is refused at ingest; split it into separate sources. |
| episode `kind` / `polarity` (`source_description`) | which records the episode carries on an edge, and their polarity | Live ingest writes one episode per source with every role it plays (`assertion`, `evidence`, `both`) and its evidence polarity. The extractor's edge cannot hold these per episode, so the episode's declaration wins. A source with both supporting and opposing evidence is refused at ingest: one episode cannot hold two polarities. |
| episode `proposition_id` (metadata / `source_description`) | which proposition an edge's records belong to | A group can hold many propositions. Records are one per episode, and each episode goes to the proposition it declares: an edge Graphiti merged from episodes of several propositions appears in each, with its own episodes. An undeclared episode belongs only when the group *is* the proposition. An episode that cannot be loaded has unknown role, polarity, time, and proposition: it never becomes a record, and every view of that group lists it in `omitted_sources` (`DEGRADED`), whether or not the group is the proposition. |
| `search()` hit set ⊂ group edges | `degraded=True`, `retrieval_scope=graphiti.search` | `RETRIEVAL_LOSS` if you forget this. |
| edge / episode `group_id` | the privacy boundary | Only edges of the adapter's `group_id` are read, even if a client's search or listing returns others; an edge that does not state its group is not trusted to be in it. Episodes that state another group are not read either (checks, conflicts, subjects, and provenance come from episodes). |
| `raw_view(..., fact_text=)` fallback | `retrieval_scope=graphiti.fact_text` (`DEGRADED`) | Used only when no edge is keyed to the proposition. A text match is similarity, not identity; an edge declared for another proposition never joins. |

The parked sidecar carries checks (with their `subjects[]`), conflicts,
lineage, completeness, freshness, and the view's `subjects[]`. Losing any of
them changes warrant; subject loss can turn a mismatched check into
`EXTERNAL`. Graphiti has no digest to check the sidecar against, so its
completeness fields are carried as written: a `degraded` that is not a
boolean, a freshness that is not an integer, or an `omitted_sources` that is
not a list makes the view invalid instead of being coerced.

Graphiti is not a snapshot store here: only the latest view is readable. Live Graphiti never replaces an episode, so each re-ingest adds a new parked sidecar; the one that applies is the newest by Graphiti's `created_at`, and two different sidecars created at the same instant make the read fail rather than pick one. Edges accumulate across ingests (Graphiti's own semantics). Use SQLite, JSON, or Mem0 when earlier `view_id`s must stay retrievable.

Both `raw_view` and `search_view` apply the parked sidecar. EWP-ingested edges
carry `roles` (`assertion`, `evidence`, or both) so an evidence-only record
does not come back as a claim and an assertion-only record does not gain
supporting evidence. Edges from Graphiti's own extractor carry no roles: each
episode's declared `kind` decides, and an episode that declares nothing is
read as both.
Live ingest writes evidence-only sources as episodes too, with
`reference_time` set from the source's `observed_at`.

Parked checks live on an episode whose *name* is `meta:{proposition_id}` and
whose body is `ewp-parked`. Graphiti assigns its own UUID. The adapter finds
that sidecar by `kind=ewp_parked`, content, or name — never by assuming the
UUID equals `meta:{pid}`.

`add_episode()` runs Graphiti’s LLM extractor. That path is lossy. Prefer
writing `lineage_id` / `origin_type` into `source_description` as:

```json
{"ewp": {"lineage_id": "scan-1", "origin_type": "tool", "proposition_id": "P-os"}}
```

Checks and conflicts are not `RELATES_TO` edges. `ingest_view_via_episodes`
parks them on a `meta:{proposition_id}` episode. If Graphiti strips
`source_description`, that is `INGEST_LOSS`, not a reason to change the protocol.

Live pin remains `graphiti-core 0.30.2`. The mapping is duck-typed so a
newer client still works if `search` / edge listing stay recognizable.

## Mem0 (`ewp/mem0_adapter.py`)

```python
from mem0 import Memory  # or MemoryClient
from ewp.mem0_adapter import Mem0Adapter

m = Memory()
adapter = Mem0Adapter(m, user_id="u1", infer=False)
adapter.ingest_view(view)
print(adapter.raw_view(view.proposition_id).checks)
print(adapter.search_view(view.proposition_id, "Windows").degraded)
```

| Mem0 field | EWP field | Notes |
|---|---|---|
| `metadata.ewp.kind=assertion` | `Assertion` | Written by `ingest_view`, one memory per assertion. Keeps `asserted_at`, `assertion_id`, confidence, and the full `SourceRef` (`source_id`, `observed_at`, `extractor_id`, …). |
| `metadata.ewp.kind=evidence` | `EvidenceItem` | One memory per evidence item. Keeps `polarity` and `observed_at`. |
| `memory` with no EWP kind | assertion + supporting evidence | Memories written outside EWP. Default `origin_type=extract` (endogenous). |
| `created_at` | fallback time only | Mem0's ingest time, not observation time. Used only when EWP metadata has none. |
| `metadata.ewp.lineage_id` | `SourceRef.lineage_id` | Falls back to memory id. |
| `metadata.ewp.origin_type` | `SourceRef.origin_type` | Only `tool` / `document` / `human` / `api` / `vendor` / `sensor` can raise EXTERNAL/HUMAN. |
| `score` | `adapter_meta.retrieval_scores` | Never warrant strength. |
| `get_all` vs `search` | `degraded` | Omitted memory ids listed. |
| sidecar `kind=ewp_parked` | checks, conflicts, lineage, completeness, `subjects[]` | Mem0 has no first-class check table. |

Reads follow the mem0ai 2.x contract: entity ids go in `filters`
(`get_all(filters={"user_id": ...})`, `search(query, filters=..., top_k=...)`),
never as top-level arguments. OSS `Memory.get_all` returns at most `top_k`
memories and does not page, so the adapter asks for `read_limit` (default
10,000) and refuses a read that comes back exactly at the limit, since it may
be truncated. The hosted `MemoryClient` pages; the adapter reads every page
and refuses a read whose total disagrees with the reported `count`.

Completeness: every snapshot read rebuilds the view from what Mem0 returned
and compares it with the digest committed in the sidecar. A lagging index, a
missing page, or an altered memory makes the read fail (`LedgerError`); it is
never returned as `retrieval_scope=complete`. A sidecar without a digest, or
without a positive integer sequence number, is refused. Memories written outside EWP
(no sidecar) have no digest to check against, so their view is
`retrieval_scope=mem0.unverified` (`DEGRADED`).

Latest: every memory also carries its ingest's sequence number. Two snapshots committed concurrently can share a sequence number; then neither is the latest, and a latest read fails until the next ingest. A read of the
latest snapshot that finds records of a newer ingest with no committed
sidecar cannot tell an interrupted ingest from a sidecar the read lost, so it
fails (`LedgerError`) instead of serving the older snapshot as current. Re-run
the interrupted ingest, or read an explicit `view_id`. Limit: Mem0 has no
transactional "latest" pointer, so a store that hides a newer snapshot
entirely (its records and its sidecar) cannot be detected by the adapter. Use
SQLite or the JSON store where the latest snapshot must be authoritative.

Snapshots: `ingest_view` tags every memory with the view's `view_id` and a
fresh `ingest_id`, and writes the parked sidecar last, with the same
`ingest_id`, a content digest, and a sequence number. A snapshot is the
memories of the one ingest its sidecar committed.
`raw_view(pid, view_id)` rebuilds exactly that snapshot and `raw_view(pid)`
the latest; `search_view` searches within one snapshot. Re-ingesting an
identical snapshot is a no-op; different content under an existing `view_id`
is refused. Memories of an ingest that never wrote its sidecar (interrupted)
are never read as part of a snapshot, and retrying the same view is safe: the
retry has a new `ingest_id`, so the orphans stay out, and once it commits the
latest read works again. Memories written outside EWP (no
`view_id`) are read only when the proposition has no EWP snapshot. Mem0 has
no transactions: two processes ingesting the same new `view_id` at the same
moment can both commit. Identical content is still one snapshot; different
content makes reads of that `view_id` fail (`LedgerError`) rather than pick
one. Give each ingest its own `view_id` (or let EWP derive one from the content).

Untagged memories (no `metadata.ewp.proposition_id`) do not enter a named
proposition view. They are `Mem0Adapter.unscoped_items()`, not evidence for P.

`infer=False` (the adapter default) stores the string you passed. `infer=True`
lets Mem0 rewrite the fact. That is convenient and usually `INGEST_LOSS`.

Platform `MemoryClient.add` is async on the server (`status=PENDING`).
The adapter does not poll events. Call `raw_view` after the event completes.

## What these adapters cannot fix

1. Provenance you did not write at ingest time.
2. Graphiti treating a later similar fact as `invalid_at` on the earlier edge.
   That is `EXPECTED_DIVERGENCE`, not a warrant of `SUPERSEDED`.
3. Ten Mem0 memories extracted from one transcript. Without a shared
   `lineage_id` they look independent. Set the lineage yourself.
4. Conformance goldens against a live extractor. Run goldens on the fake
   store / `infer=False` path. Use live clients for integration tests.

## Failure classes (same as CONFORMANCE.md)

| Class | Typical live cause |
|---|---|
| `INGEST_LOSS` | Graphiti extractor dropped metadata; Mem0 `infer=True` rewrote text |
| `ADAPTER_MAP_LOSS` | Episode uuid on an edge but episode node missing |
| `WARRANT_MISMATCH` | You treated `invalid_at` or `score` as an axis |
| `RETRIEVAL_LOSS` | Search view not marked `degraded` |
| `EXPECTED_DIVERGENCE` | Store “current fact” ≠ `warrant_now` |
