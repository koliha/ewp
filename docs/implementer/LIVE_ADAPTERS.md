# Live Graphiti and Mem0 adapters

v0.2.0 ships fake Graphiti + SQLite + JSON so the kernel can freeze without
Neo4j or a Mem0 key. These adapters are the production mapping.

```
store client  →  EvidenceView  →  warrant_now(view, policy, evaluated_at)
```

Neither adapter is a second epistemology. Graphiti `invalid_at` and Mem0
`score` stay in `adapter_meta` / evidence notes. They never become axes.

## Graphiti (`protocol/graphiti_client_adapter.py`)

```python
from protocol.graphiti_client_adapter import GraphitiClientAdapter
from protocol.types import Policy
from protocol.warrant import warrant_now

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

## Mem0 (`protocol/mem0_adapter.py`)

```python
from mem0 import Memory  # or MemoryClient
from protocol.mem0_adapter import Mem0Adapter

m = Memory()
adapter = Mem0Adapter(m, user_id="u1", infer=False)
adapter.ingest_view(view)
print(adapter.raw_view(view.proposition_id).checks)
print(adapter.search_view(view.proposition_id, "Windows").degraded)
```

| Mem0 field | EWP field | Notes |
|---|---|---|
| `memory` | assertion + supporting evidence | Default `origin_type=extract` (endogenous). |
| `metadata.ewp.lineage_id` | `SourceRef.lineage_id` | Falls back to memory id. |
| `metadata.ewp.origin_type` | `SourceRef.origin_type` | Only `tool` / `document` / `human` / `api` / `vendor` / `sensor` can raise EXTERNAL/HUMAN. |
| `score` | `adapter_meta.retrieval_scores` | Never warrant strength. |
| `get_all` vs `search` | `degraded` | Omitted memory ids listed. |
| sidecar `kind=ewp_parked` | checks, conflicts, lineage | Mem0 has no first-class check table. |

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
