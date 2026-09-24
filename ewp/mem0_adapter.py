"""Live Mem0 → EvidenceView adapter.

Works with:
  * `mem0.Memory` (OSS)
  * `mem0.MemoryClient` (platform)
  * any duck type exposing add / search / get_all / get

Mem0 stores extracted memories, not EWP records. Mapping rules:

* Default `origin_type` is `extract` (endogenous). Mem0's LLM extractor
  cannot manufacture EXTERNAL or HUMAN verification.
* `infer=False` on add keeps the raw string; still origin `extract`
  unless metadata supplies a trusted origin.
* Retrieval score is adapter_meta only. Never warrant strength.
* A search that returns fewer of the snapshot's memories ⇒ `degraded=True`.
* EWP ingest writes assertions (`kind=assertion`) and evidence
  (`kind=evidence`) as separate memories. Each keeps its own polarity and
  its original asserted_at / observed_at; Mem0's created_at is ingest
  time, not observation time. A plain memory (`kind=memory`, written
  outside EWP) maps to an assertion plus supporting evidence.
* Checks / conflicts are parked as sibling memories with
  `metadata.ewp.kind` in {ewp_check, ewp_conflict, ewp_parked}.
* Snapshots: `ingest_view` tags every memory with the view's `view_id`, a
  fresh `ingest_id`, and a sequence number, and writes the parked sidecar
  last with the same ids and a content digest. `raw_view(pid, view_id)`
  rebuilds exactly that snapshot and checks it against the digest;
  `raw_view(pid)` the latest, refused when a newer uncommitted ingest or a
  sequence tie makes "latest" unknowable. Re-ingesting an identical snapshot
  is a no-op; different content under an existing `view_id` is refused.
  Memories of an interrupted ingest are never read. Memories written outside
  EWP (no `view_id`) are read only when the proposition has no EWP snapshot,
  as `retrieval_scope=mem0.unverified` (DEGRADED).
"""

from __future__ import annotations

import inspect
import uuid
from typing import Any

from .live_util import (
    EWP_META_KEY,
    as_dict,
    as_list,
    attr,
    ewp_blob,
    observed_time,
    unwrap_collection,
)
from .classify import InvalidEvidenceView, validate_view
from .codec import _number, content_view_id, record_identity_conflicts, subjects_from
from .sqlite_adapter import ImmutableRecordError, LedgerError, MissingViewError
from .types import (
    Assertion,
    Conflict,
    EvidenceItem,
    EvidenceView,
    LineageEdge,
    SourceRef,
    VerificationCheck,
)


# Kinds that carry evidence text (as opposed to parked sidecars).
MEMORY_KINDS = frozenset({"memory", "assertion", "evidence"})


def _kind(item: Any) -> str:
    return str(ewp_blob(item).get("kind") or "memory")


def _item_id(item: Any) -> str:
    return str(attr(item, "id", "memory_id", "uuid", default="") or "")


def _item_text(item: Any) -> str:
    return str(attr(item, "memory", "text", "data", "content", default="") or "")


def _item_when(item: Any) -> str:
    return observed_time(attr(item, "created_at", "updated_at", "timestamp", default=None))


def _item_score(item: Any) -> float | None:
    value = attr(item, "score", default=None)
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _given(blob: dict[str, Any], key: str, default: Any) -> Any:
    """The written value, even when falsy (""); the default only when absent.
    EWP-written memories must read back exactly what was written."""
    value = blob.get(key)
    return default if value is None else value


def source_from_mem0(item: Any, *, fallback_id: str) -> SourceRef:
    """EWP-written memories carry the original SourceRef in metadata and get
    it back exactly. Memories written outside EWP get Mem0-derived defaults."""
    blob = ewp_blob(item)
    mid = _item_id(item) or fallback_id
    return SourceRef(
        source_id=str(_given(blob, "source_id", mid)),
        lineage_id=str(_given(blob, "lineage_id", mid)),
        origin_type=str(_given(blob, "origin_type", "extract")),
        origin_locator=str(_given(blob, "origin_locator", f"mem0:memory:{mid}")),
        snapshot_id=str(_given(blob, "snapshot_id", mid)),
        content_hash=str(_given(blob, "content_hash", attr(item, "hash", default=f"mem0:{mid}"))),
        observed_at=str(_given(blob, "source_observed_at", _item_when(item))),
        extractor_id=blob["extractor_id"] if "extractor_id" in blob else "mem0.extract",
        parent_source_id=blob.get("parent_source_id"),
    )


def items_to_view(
    items: list[Any],
    *,
    proposition_id: str,
    view_id: str | None,
    retrieval_scope: str,
    raw_count: int | None = None,
    omitted: list[str] | None = None,
) -> EvidenceView:
    assertions: list[Assertion] = []
    evidence: list[EvidenceItem] = []
    checks: list[VerificationCheck] = []
    conflicts: list[Conflict] = []
    lineage: list[LineageEdge] = []
    parked_omitted: list[str] = []
    degraded = False
    freshness = 86400 * 30
    subjects: Any = ()
    parked_view_id: str | None = None
    scores: dict[str, float] = {}
    scope = retrieval_scope

    for i, item in enumerate(items):
        blob = ewp_blob(item)
        kind = str(blob.get("kind") or "memory")
        mid = _item_id(item) or f"mem0-{i}"
        when = _item_when(item)
        src = source_from_mem0(item, fallback_id=mid)
        score = _item_score(item)
        if score is not None:
            scores[mid] = score

        if kind == "ewp_parked":
            checks.extend(_checks_from_blob(blob))
            conflicts.extend(_conflicts_from_blob(blob))
            lineage.extend(_lineage_from_blob(blob))
            parked = blob.get("omitted_sources")
            if isinstance(parked, list):
                parked_omitted.extend(parked)
            elif parked is not None:
                raise InvalidEvidenceView(f"parked omitted_sources={parked!r} must be a list of strings")
            degraded = degraded or blob.get("degraded") is True
            if blob.get("retrieval_scope") is not None and scope == "complete":
                scope = blob["retrieval_scope"]
            if blob.get("freshness_policy_seconds") is not None:
                freshness = blob["freshness_policy_seconds"]
            subjects = subjects_from(blob.get("subjects"))
            parked_view_id = blob.get("view_id") or None
            continue

        if kind == "ewp_check":
            checks.append(
                VerificationCheck(
                    check_id=str(blob.get("check_id") or mid),
                    method=str(blob.get("method") or "extract"),
                    scope=str(blob.get("scope") or proposition_id),
                    source=src,
                    observed_at=str(_given(blob, "observed_at", when)),
                    result=blob.get("result") or "inconclusive",  # type: ignore[arg-type]
                    subjects=subjects_from(blob.get("subjects")),
                )
            )
            continue

        if kind == "ewp_conflict":
            conflicts.append(
                Conflict(
                    str(blob.get("conflict_id") or mid),
                    tuple(str(x) for x in as_list(blob.get("proposition_ids") or [proposition_id])),
                    blob.get("status") or "open",  # type: ignore[arg-type]
                    str(blob.get("note") or ""),
                )
            )
            continue

        if kind == "ewp_lineage":
            lineage.append(
                LineageEdge(
                    str(blob.get("from") or blob.get("from_id") or ""),
                    str(blob.get("to") or blob.get("to_id") or ""),
                    blob.get("kind_edge") or blob.get("edge_kind") or "derived_from",  # type: ignore[arg-type]
                )
            )
            continue

        # The record's own proposition (may be a variant pid:<suffix>); the
        # tag `proposition_id` is the view the memory belongs to.
        prop = str(_given(blob, "record_proposition_id", _given(blob, "proposition_id", proposition_id)))
        text = _item_text(item)
        polarity = _given(blob, "polarity", "supports")
        if kind in {"memory", "assertion"}:
            assertions.append(
                Assertion(
                    assertion_id=str(_given(blob, "assertion_id", f"{mid}:a")),
                    proposition_id=prop,
                    text=text,
                    asserted_by=str(_given(blob, "asserted_by", "mem0.extract")),
                    assertion_confidence=_number(_given(blob, "assertion_confidence", 0.5)),
                    source=src,
                    asserted_at=str(_given(blob, "asserted_at", when)),
                )
            )
        if kind in {"memory", "evidence"}:
            evidence.append(
                EvidenceItem(
                    evidence_id=str(_given(blob, "evidence_id", f"{mid}:e")),
                    proposition_id=prop,
                    polarity=polarity,  # type: ignore[arg-type]
                    source=src,
                    content=text,
                    observed_at=str(_given(blob, "observed_at", when)),
                )
            )

    if raw_count is not None and raw_count > len(
        [it for it in items if _kind(it) in MEMORY_KINDS]
    ):
        degraded = True
        scope = "mem0.search"

    return EvidenceView(
        view_id=view_id or parked_view_id or "mem0",
        proposition_id=proposition_id,
        assertions=assertions,
        evidence=evidence,
        lineage=lineage,
        conflicts=conflicts,
        checks=checks,
        omitted_sources=list(omitted or []) + parked_omitted,
        retrieval_scope=scope,
        degraded=degraded,
        freshness_policy_seconds=freshness,
        adapter_meta={"store": "mem0", "retrieval_scores": scores},
        subjects=subjects,
    )


def _checks_from_blob(blob: dict[str, Any]) -> list[VerificationCheck]:
    out: list[VerificationCheck] = []
    for c in blob.get("checks") or []:
        src = c.get("source") or {}
        fields = tuple(SourceRef.__dataclass_fields__)
        out.append(
            VerificationCheck(
                check_id=c["check_id"],
                method=c["method"],
                scope=c["scope"],
                source=SourceRef(**{k: src[k] for k in fields}),
                observed_at=c["observed_at"],
                result=c["result"],
                subjects=subjects_from(c.get("subjects")),
            )
        )
    return out


def _conflicts_from_blob(blob: dict[str, Any]) -> list[Conflict]:
    return [
        Conflict(c["conflict_id"], tuple(c["proposition_ids"]), c["status"], c.get("note", ""))
        for c in blob.get("conflicts") or []
    ]


def _lineage_from_blob(blob: dict[str, Any]) -> list[LineageEdge]:
    return [
        LineageEdge(e.get("from") or e.get("from_id"), e.get("to") or e.get("to_id"), e["kind"])
        for e in blob.get("lineage") or []
    ]


DEFAULT_READ_LIMIT = 10_000
HOSTED_PAGE_SIZE = 100


def _seq(item: Any) -> int:
    """A snapshot sequence number: a positive integer. Missing or malformed is
    a damaged store, never 0 (which would quietly demote a snapshot below
    older ones and let "latest" pick a stale view)."""
    raw = ewp_blob(item).get("seq")
    if raw is None or isinstance(raw, bool) or not isinstance(raw, (int, str)):
        raise LedgerError(f"Mem0 memory {_item_id(item)!r} has a missing or malformed seq {raw!r}")
    try:
        value = int(raw)
    except ValueError as exc:
        raise LedgerError(f"Mem0 memory {_item_id(item)!r} has a malformed seq {raw!r}") from exc
    if value < 1:
        raise LedgerError(f"Mem0 memory {_item_id(item)!r} has a non-positive seq {raw!r}")
    return value


class Mem0Adapter:
    """Adapter around a Mem0 2.x client: OSS `mem0.Memory` or hosted
    `mem0.MemoryClient`.

    Reads use the 2.x contract: entity ids go in `filters`, never as
    top-level arguments. OSS `get_all` returns at most `top_k` memories with
    no paging, so a read that comes back exactly at `read_limit` may be
    truncated and is refused. The hosted client pages; every page is read.
    A snapshot is only returned once it matches the digest committed in its
    sidecar, so a partial read fails closed instead of posing as complete.
    """

    def __init__(
        self,
        client: Any,
        *,
        user_id: str,
        agent_id: str | None = None,
        run_id: str | None = None,
        infer: bool = False,
        read_limit: int = DEFAULT_READ_LIMIT,
    ) -> None:
        self.client = client
        self.user_id = user_id
        self.agent_id = agent_id
        self.run_id = run_id
        self.infer = infer
        self.read_limit = read_limit
        self.page_size = HOSTED_PAGE_SIZE

    def _scope(self) -> dict[str, Any]:
        kw: dict[str, Any] = {"user_id": self.user_id}
        if self.agent_id:
            kw["agent_id"] = self.agent_id
        if self.run_id:
            kw["run_id"] = self.run_id
        return kw

    def _filters(self) -> dict[str, Any]:
        """Mem0 2.x read filters: the entity ids (at least user_id)."""
        return dict(self._scope())

    def _paginated(self) -> bool:
        """Hosted MemoryClient.get_all pages (page/page_size); OSS Memory.get_all takes top_k."""
        try:
            params = inspect.signature(self.client.get_all).parameters
        except (TypeError, ValueError):
            return False
        return "top_k" not in params

    def _all_items(self) -> list[Any]:
        if not self._paginated():
            payload = self.client.get_all(filters=self._filters(), top_k=self.read_limit)
            items = unwrap_collection(payload)
            if len(items) >= self.read_limit:
                raise LedgerError(
                    f"Mem0 get_all returned {len(items)} memories, the read limit; the read may be "
                    "truncated. Raise read_limit."
                )
            return items
        items: list[Any] = []
        page = 1
        while True:
            payload = self.client.get_all(filters=self._filters(), page=page, page_size=self.page_size)
            batch = unwrap_collection(payload)
            items.extend(batch)
            if len(items) > self.read_limit:
                raise LedgerError(f"Mem0 get_all passed read_limit={self.read_limit}; raise read_limit")
            if not batch or not (isinstance(payload, dict) and payload.get("next")):
                break
            page += 1
        count = payload.get("count") if isinstance(payload, dict) else None
        if isinstance(count, int) and count != len(items):
            raise LedgerError(f"Mem0 get_all reported {count} memories but returned {len(items)}; retry the read")
        return items

    def _search_items(self, query: str, limit: int) -> list[Any]:
        payload = self.client.search(query, filters=self._filters(), top_k=limit)
        return unwrap_collection(payload)

    def _verified(self, members: list[Any], car: Any, proposition_id: str) -> EvidenceView:
        """The snapshot this sidecar committed, rebuilt from what the store
        returned. If the store returned fewer (or other) records than were
        committed, the digest differs and the read is refused."""
        blob = ewp_blob(car)
        if not blob.get("digest"):
            raise LedgerError(
                f"Mem0 snapshot {blob['view_id']!r} of {proposition_id!r} has no digest; "
                "it cannot be checked and is not read"
            )
        view = items_to_view(
            members + [car],
            proposition_id=proposition_id,
            view_id=blob["view_id"],
            retrieval_scope="complete",
        )
        if content_view_id(view) != blob["digest"]:
            raise LedgerError(
                f"Mem0 returned an incomplete or altered snapshot {blob['view_id']!r} of {proposition_id!r}: "
                "its records do not match the digest committed at ingest"
            )
        return view

    def _for_proposition(self, items: list[Any], proposition_id: str) -> list[Any]:
        """Only memories tagged with this proposition_id.

        Untagged Mem0 extracts have no EWP identity. Including them in every
        view is an unscoped leak (ADAPTER_MAP_LOSS / false corroboration).
        """
        matched = []
        for item in items:
            blob = ewp_blob(item)
            if blob.get("proposition_id") == proposition_id:
                matched.append(item)
        return matched

    def unscoped_items(self) -> list[Any]:
        """Memories with no ewp.proposition_id. Not evidence for any P."""
        out = []
        for item in self._all_items():
            blob = ewp_blob(item)
            if not blob.get("proposition_id"):
                out.append(item)
        return out

    def _sidecars(self, items: list[Any]) -> list[Any]:
        """EWP snapshot sidecars for a proposition, oldest first."""
        cars = [it for it in items if _kind(it) == "ewp_parked" and ewp_blob(it).get("view_id")]
        return sorted(cars, key=lambda it: (_seq(it), str(ewp_blob(it).get("ingest_id") or "")))

    @staticmethod
    def _sidecar_for(cars: list[Any], proposition_id: str, view_id: str) -> Any:
        """The one committed sidecar for view_id. Two ingests racing on a new
        view_id can both commit; identical content is one snapshot, different
        content is refused rather than silently picking a winner."""
        matching = [c for c in cars if ewp_blob(c).get("view_id") == view_id]
        if not matching:
            raise MissingViewError(f"no stored view for {proposition_id!r} with view_id {view_id!r}")
        if len({ewp_blob(c).get("digest") for c in matching}) > 1:
            raise LedgerError(
                f"view {view_id!r} of {proposition_id!r} was committed twice with different content "
                "(concurrent ingest); re-ingest under a new view_id"
            )
        return matching[0]

    def _snapshot(self, proposition_id: str, view_id: str | None) -> tuple[list[Any], str | None, Any]:
        """(member memories, snapshot view_id, sidecar).

        With no completed EWP snapshot, fall back to memories written outside
        EWP (no view_id tag). Memories tagged with a view_id belong to an EWP
        snapshot; without its sidecar that snapshot is incomplete and unread.
        """
        items = self._for_proposition(self._all_items(), proposition_id)
        cars = self._sidecars(items)
        if not cars:
            if view_id is not None:
                raise MissingViewError(f"no stored view for {proposition_id!r} with view_id {view_id!r}")
            return [it for it in items if not ewp_blob(it).get("view_id")], None, None
        if view_id is None:
            self._check_latest(items, cars, proposition_id)
        chosen = ewp_blob(cars[-1])["view_id"] if view_id is None else view_id
        car = self._sidecar_for(cars, proposition_id, chosen)
        return self._members_of(items, car), chosen, car

    @staticmethod
    def _check_latest(items: list[Any], cars: list[Any], proposition_id: str) -> None:
        """The newest committed sidecar is the latest snapshot only if no newer
        ingest left records behind. Records from an ingest with a higher
        sequence and no committed sidecar mean either an interrupted ingest or
        a sidecar this read lost; either way "latest" cannot be established,
        so the read is refused rather than serving an older snapshot as
        current. (A store that hides a newer snapshot entirely, records and
        sidecar, cannot be detected: Mem0 has no transactional latest pointer.)"""
        committed = {str(ewp_blob(c).get("ingest_id")) for c in cars}
        newest = _seq(cars[-1])
        tied = sorted({str(ewp_blob(c).get("view_id")) for c in cars if _seq(c) == newest})
        if len(tied) > 1:
            raise LedgerError(
                f"{proposition_id!r}: snapshots {tied} were committed concurrently with the same sequence "
                "number, so none of them is the latest. Read an explicit view_id, or ingest a new snapshot."
            )
        pending = sorted({
            str(ewp_blob(it).get("ingest_id"))
            for it in items
            if _kind(it) in MEMORY_KINDS
            and ewp_blob(it).get("view_id")
            and ewp_blob(it).get("seq") is not None
            and _seq(it) > newest
            and str(ewp_blob(it).get("ingest_id")) not in committed
        })
        if pending:
            raise LedgerError(
                f"{proposition_id!r}: Mem0 holds records of a newer ingest with no committed snapshot "
                f"(ingest {', '.join(pending)}): an interrupted ingest (re-run it) or a snapshot this read "
                "lost. The latest snapshot cannot be established; read an explicit view_id instead."
            )

    @staticmethod
    def _members_of(items: list[Any], car: Any) -> list[Any]:
        """Memories of exactly the ingest this sidecar committed. Records left
        by an interrupted attempt at the same view_id carry another ingest_id."""
        blob = ewp_blob(car)
        return [
            it for it in items
            if _kind(it) in MEMORY_KINDS
            and ewp_blob(it).get("view_id") == blob["view_id"]
            and ewp_blob(it).get("ingest_id") == blob.get("ingest_id")
        ]

    def raw_view(
        self,
        proposition_id: str,
        view_id: str | None = None,
    ) -> EvidenceView:
        """Exactly the stored snapshot; the latest one when view_id is None.

        Memories written outside EWP (no snapshot sidecar) have no manifest to
        check the read against, so that view is never called complete."""
        members, chosen, car = self._snapshot(proposition_id, view_id)
        if car is not None:
            return self._verified(members, car, proposition_id)
        return items_to_view(
            members,
            proposition_id=proposition_id,
            view_id=chosen,
            retrieval_scope="mem0.unverified",
        )

    def search_view(
        self,
        proposition_id: str,
        query: str,
        view_id: str | None = None,
        limit: int = 20,
    ) -> EvidenceView:
        """Search within one snapshot (the latest by default). Dropped members
        are listed in omitted_sources and mark the view DEGRADED."""
        members, chosen, car = self._snapshot(proposition_id, view_id)
        if car is not None:
            self._verified(members, car, proposition_id)
        member_ids = {_item_id(m) for m in members if _kind(m) in MEMORY_KINDS}
        hits = [h for h in self._for_proposition(self._search_items(query, limit), proposition_id) if _item_id(h) in member_ids]
        omitted = sorted(member_ids - {_item_id(h) for h in hits})
        parked = [car] if car is not None else [m for m in members if _kind(m).startswith("ewp_")]
        raw_ids = member_ids
        combined = list(hits) + parked
        view = items_to_view(
            combined,
            proposition_id=proposition_id,
            view_id=f"{chosen or 'mem0'}#search",
            retrieval_scope="mem0.search",
            raw_count=len(raw_ids),
            omitted=omitted,
        )
        if omitted:
            view.degraded = True
        return view

    def ingest_view(self, view: EvidenceView) -> dict[str, Any]:
        """Write assertions and evidence as Mem0 memories + one parked sidecar.

        One memory per record, so polarity and timestamps survive. Uses
        infer=False by default so Mem0 does not rewrite the text.
        """
        validate_view(view)
        report = {"memories": 0, "checks_parked": 0, "conflicts_parked": 0, "infer": self.infer, "stored": True}
        digest = content_view_id(view)
        items = self._for_proposition(self._all_items(), view.proposition_id)
        cars = self._sidecars(items)
        for car in cars:
            blob = ewp_blob(car)
            if blob.get("view_id") == view.view_id:
                if blob.get("digest") != digest:
                    raise ImmutableRecordError(
                        f"view {view.view_id!r} of {view.proposition_id!r} is an immutable snapshot with different content"
                    )
                report["stored"] = False  # identical snapshot already present
                return report
        # Every committed sidecar on its own, including both sides of a racing
        # commit, so one bad view_id cannot block later snapshots.
        stored = [self._verified(self._members_of(items, c), c, view.proposition_id) for c in cars]
        clashes = record_identity_conflicts(stored, view)
        if clashes:
            raise ImmutableRecordError(
                f"{view.proposition_id!r}: ids already name different records in earlier snapshots: {', '.join(clashes)}"
            )
        seq = 1 + max((_seq(c) for c in cars), default=0)
        # Tags every memory of this attempt. A retry after an interrupted
        # ingest gets a new id, so the orphans of the failed attempt stay out.
        ingest_id = uuid.uuid4().hex

        def source_meta(src: SourceRef) -> dict[str, Any]:
            return {
                "proposition_id": view.proposition_id,
                "view_id": view.view_id,
                "ingest_id": ingest_id,
                "seq": seq,
                "lineage_id": src.lineage_id,
                "origin_type": src.origin_type,
                "origin_locator": src.origin_locator,
                "content_hash": src.content_hash,
                "parent_source_id": src.parent_source_id,
                "extractor_id": src.extractor_id,
                "snapshot_id": src.snapshot_id,
                "source_id": src.source_id,
                "source_observed_at": src.observed_at,
            }

        for assertion in view.assertions:
            metadata = {
                EWP_META_KEY: {
                    **source_meta(assertion.source),
                    "record_proposition_id": assertion.proposition_id,
                    "kind": "assertion",
                    "assertion_id": assertion.assertion_id,
                    "asserted_by": assertion.asserted_by,
                    "assertion_confidence": assertion.assertion_confidence,
                    "asserted_at": assertion.asserted_at,
                }
            }
            self._add(assertion.text, metadata)
            report["memories"] += 1

        for ev in view.evidence:
            metadata = {
                EWP_META_KEY: {
                    **source_meta(ev.source),
                    "record_proposition_id": ev.proposition_id,
                    "kind": "evidence",
                    "evidence_id": ev.evidence_id,
                    "polarity": ev.polarity,
                    "observed_at": ev.observed_at,
                }
            }
            self._add(ev.content, metadata)
            report["memories"] += 1

        park = {
            EWP_META_KEY: {
                "kind": "ewp_parked",
                "proposition_id": view.proposition_id,
                "checks": [
                    {**c.__dict__, "source": c.source.__dict__, "subjects": list(c.subjects)}
                    for c in view.checks
                ],
                "conflicts": [
                    {
                        "conflict_id": c.conflict_id,
                        "proposition_ids": list(c.proposition_ids),
                        "status": c.status,
                        "note": c.note,
                    }
                    for c in view.conflicts
                ],
                "lineage": [
                    {"from": e.from_id, "to": e.to_id, "kind": e.kind} for e in view.lineage
                ],
                "omitted_sources": view.omitted_sources,
                "degraded": view.degraded,
                "retrieval_scope": view.retrieval_scope,
                "freshness_policy_seconds": view.freshness_policy_seconds,
                "subjects": list(view.subjects),
                "view_id": view.view_id,
                "ingest_id": ingest_id,
                "digest": digest,
                "seq": seq,
            }
        }
        # Written last: a snapshot exists only once all its memories do.
        self._add(f"ewp-parked:{view.proposition_id}", park)
        report["checks_parked"] = len(view.checks)
        report["conflicts_parked"] = len(view.conflicts)
        return report

    def _add(self, text: str, metadata: dict[str, Any]) -> Any:
        messages = [{"role": "user", "content": text}]
        # Called once. A retry here could write the memory twice under one
        # ingest_id, and that snapshot would then never match its digest.
        return self.client.add(messages, **self._scope(), metadata=metadata, infer=self.infer)
