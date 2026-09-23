# Live Graphiti and Mem0 adapters

EWP-0.2.0 ships fake Graphiti + SQLite + JSON so the kernel can be locked
without Neo4j or a Mem0 key. The Mem0 adapter is the production mapping for
Mem0. The live Graphiti adapter is **experimental**: it has not been run
against a real `graphiti-core`, whose `add_episode()` LLM extractor decides
which fields survive.
`tests/test_adapter_roundtrip.py` runs every fixture through the fake
Graphiti and Mem0 paths and requires identical axes. Mem0 must also return
every field unchanged; fake Graphiti may lose only the fields listed in
`GRAPHITI_FIELD_LOSSES` (record ids, asserter, confidence, evidence content,
duplicate identical assertions).

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
| `EntityEdge.episodes[]` | `SourceRef.source_id` | One assertion per episode on the edge. |
| `EpisodicNode.metadata.lineage_id` or `source_description` JSON | `SourceRef.lineage_id` | Must be written by the caller. Graphiti must not invent it. |
| `valid_at` / `invalid_at` / `expired_at` | evidence note only | Store-local. Not currency, not verification. |
| `search()` hit set ⊂ group edges | `degraded=True`, `retrieval_scope=graphiti.search` | `RETRIEVAL_LOSS` if you forget this. |

The parked sidecar carries checks (with their `subjects[]`), conflicts,
lineage, completeness, freshness, and the view's `subjects[]`. Losing any of
them changes warrant; subject loss can turn a mismatched check into
`EXTERNAL`.

Graphiti is not a snapshot store here: each proposition has one parked sidecar, and re-ingesting replaces it, so only the latest view is readable. Use SQLite, JSON, or Mem0 when earlier `view_id`s must stay retrievable.

Both `raw_view` and `search_view` apply the parked sidecar. EWP-ingested edges
carry `roles` (`assertion`, `evidence`, or both) so an evidence-only record
does not come back as a claim and an assertion-only record does not gain
supporting evidence. Edges from Graphiti's own extractor are read as both.
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

Snapshots: `ingest_view` tags every memory with the view's `view_id` and
writes the parked sidecar last, with a content digest and a sequence number.
`raw_view(pid, view_id)` rebuilds exactly that snapshot and `raw_view(pid)`
the latest; `search_view` searches within one snapshot. Re-ingesting an
identical snapshot is a no-op; different content under an existing `view_id`
is refused. Memories tagged with a `view_id` but no sidecar (an interrupted
ingest) are never read. Memories written outside EWP (no `view_id`) are read
only when the proposition has no EWP snapshot. Mem0 has no transactions: two
processes ingesting the same new `view_id` at the same moment can both write
it, and the resulting view is refused at evaluation for duplicate ids. Give
each ingest its own `view_id` (or let EWP derive one from the content).

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
