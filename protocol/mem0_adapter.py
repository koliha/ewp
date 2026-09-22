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
* `search` vs `get_all` length mismatch ⇒ `degraded=True`.
* Checks / conflicts are parked as sibling memories with
  `metadata.ewp.kind` in {ewp_check, ewp_conflict, ewp_parked}.
"""

from __future__ import annotations

from typing import Any

from .live_util import (
    EWP_META_KEY,
    as_dict,
    as_list,
    attr,
    ewp_blob,
    iso,
    unwrap_collection,
)
from .types import (
    Assertion,
    Conflict,
    EvidenceItem,
    EvidenceView,
    LineageEdge,
    SourceRef,
    VerificationCheck,
)


def _item_id(item: Any) -> str:
    return str(attr(item, "id", "memory_id", "uuid", default="") or "")


def _item_text(item: Any) -> str:
    return str(attr(item, "memory", "text", "data", "content", default="") or "")


def _item_when(item: Any) -> str:
    return iso(attr(item, "created_at", "updated_at", "timestamp", default=None))


def _item_score(item: Any) -> float | None:
    value = attr(item, "score", default=None)
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def source_from_mem0(item: Any, *, fallback_id: str) -> SourceRef:
    blob = ewp_blob(item)
    mid = _item_id(item) or fallback_id
    origin = str(blob.get("origin_type") or "extract")
    lineage = str(blob.get("lineage_id") or mid)
    locator = str(blob.get("origin_locator") or f"mem0:memory:{mid}")
    digest = str(blob.get("content_hash") or attr(item, "hash", default=f"mem0:{mid}"))
    return SourceRef(
        source_id=mid,
        lineage_id=lineage,
        origin_type=origin,
        origin_locator=locator,
        snapshot_id=str(blob.get("snapshot_id") or mid),
        content_hash=str(digest),
        observed_at=_item_when(item),
        extractor_id=blob.get("extractor_id") or "mem0.extract",
        parent_source_id=blob.get("parent_source_id"),
    )


def items_to_view(
    items: list[Any],
    *,
    proposition_id: str,
    view_id: str,
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
            parked_omitted.extend(str(x) for x in blob.get("omitted_sources") or [])
            degraded = degraded or bool(blob.get("degraded", False))
            if blob.get("retrieval_scope"):
                scope = str(blob["retrieval_scope"])
            if blob.get("freshness_policy_seconds") is not None:
                freshness = int(blob["freshness_policy_seconds"])
            continue

        if kind == "ewp_check":
            checks.append(
                VerificationCheck(
                    check_id=str(blob.get("check_id") or mid),
                    method=str(blob.get("method") or "extract"),
                    scope=str(blob.get("scope") or proposition_id),
                    source=src,
                    observed_at=str(blob.get("observed_at") or when),
                    result=blob.get("result") or "inconclusive",  # type: ignore[arg-type]
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

        prop = str(blob.get("proposition_id") or proposition_id)
        text = _item_text(item)
        polarity = blob.get("polarity") or "supports"
        assertions.append(
            Assertion(
                assertion_id=f"{mid}:a",
                proposition_id=prop,
                text=text,
                asserted_by=str(blob.get("asserted_by") or "mem0.extract"),
                assertion_confidence=float(blob.get("assertion_confidence") or 0.5),
                source=src,
                asserted_at=when,
            )
        )
        evidence.append(
            EvidenceItem(
                evidence_id=f"{mid}:e",
                proposition_id=prop,
                polarity=polarity,  # type: ignore[arg-type]
                source=src,
                content=text,
                observed_at=when,
            )
        )

    if raw_count is not None and raw_count > len(
        [it for it in items if str(ewp_blob(it).get("kind") or "memory") == "memory"]
    ):
        degraded = True
        scope = "mem0.search"

    return EvidenceView(
        view_id=view_id,
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


class Mem0Adapter:
    """Production adapter around a Mem0 client."""

    def __init__(
        self,
        client: Any,
        *,
        user_id: str,
        agent_id: str | None = None,
        run_id: str | None = None,
        infer: bool = False,
    ) -> None:
        self.client = client
        self.user_id = user_id
        self.agent_id = agent_id
        self.run_id = run_id
        self.infer = infer

    def _scope(self) -> dict[str, Any]:
        kw: dict[str, Any] = {"user_id": self.user_id}
        if self.agent_id:
            kw["agent_id"] = self.agent_id
        if self.run_id:
            kw["run_id"] = self.run_id
        return kw

    def _call(self, method: str, *args: Any, **kwargs: Any) -> Any:
        fn = getattr(self.client, method)
        try:
            return fn(*args, **kwargs)
        except TypeError:
            # Platform client is picky about unused kwargs.
            slim = {k: v for k, v in kwargs.items() if v is not None}
            return fn(*args, **slim)

    def _all_items(self) -> list[Any]:
        payload = self._call("get_all", **self._scope())
        return unwrap_collection(payload)

    def _search_items(self, query: str, limit: int) -> list[Any]:
        payload = self._call("search", query, limit=limit, **self._scope())
        return unwrap_collection(payload)

    def _for_proposition(self, items: list[Any], proposition_id: str) -> list[Any]:
        matched = []
        for item in items:
            blob = ewp_blob(item)
            prop = blob.get("proposition_id")
            if prop is None or prop == proposition_id:
                matched.append(item)
        return matched

    def raw_view(
        self,
        proposition_id: str,
        view_id: str = "mem0-raw",
    ) -> EvidenceView:
        items = self._for_proposition(self._all_items(), proposition_id)
        return items_to_view(
            items,
            proposition_id=proposition_id,
            view_id=view_id,
            retrieval_scope="complete",
        )

    def search_view(
        self,
        proposition_id: str,
        query: str,
        view_id: str = "mem0-search",
        limit: int = 20,
    ) -> EvidenceView:
        raw = self._for_proposition(self._all_items(), proposition_id)
        hits = self._search_items(query, limit)
        hit_ids = {_item_id(h) for h in hits}
        raw_ids = {_item_id(r) for r in raw if str(ewp_blob(r).get("kind") or "memory") == "memory"}
        omitted = sorted(raw_ids - hit_ids)
        # Keep parked sidecar records so checks/conflicts survive search.
        parked = [
            it
            for it in raw
            if str(ewp_blob(it).get("kind") or "memory").startswith("ewp_")
        ]
        combined = list(hits) + parked
        view = items_to_view(
            combined,
            proposition_id=proposition_id,
            view_id=view_id,
            retrieval_scope="mem0.search",
            raw_count=len(raw_ids),
            omitted=omitted,
        )
        if omitted:
            view.degraded = True
        return view

    def ingest_view(self, view: EvidenceView) -> dict[str, Any]:
        """Write assertions as Mem0 memories + one parked sidecar.

        Uses infer=False by default so Mem0 does not rewrite the text.
        """
        report = {"memories": 0, "checks_parked": 0, "conflicts_parked": 0, "infer": self.infer}
        seen: set[str] = set()
        for assertion in view.assertions:
            src = assertion.source
            if src.source_id in seen:
                continue
            seen.add(src.source_id)
            metadata = {
                EWP_META_KEY: {
                    "kind": "memory",
                    "proposition_id": view.proposition_id,
                    "lineage_id": src.lineage_id,
                    "origin_type": src.origin_type,
                    "origin_locator": src.origin_locator,
                    "content_hash": src.content_hash,
                    "parent_source_id": src.parent_source_id,
                    "extractor_id": src.extractor_id,
                    "snapshot_id": src.snapshot_id,
                    "asserted_by": assertion.asserted_by,
                    "assertion_confidence": assertion.assertion_confidence,
                    "polarity": "supports",
                }
            }
            self._add(assertion.text, metadata)
            report["memories"] += 1

        for ev in view.evidence:
            if ev.source.source_id in seen:
                continue
            seen.add(ev.source.source_id)
            metadata = {
                EWP_META_KEY: {
                    "kind": "memory",
                    "proposition_id": view.proposition_id,
                    "lineage_id": ev.source.lineage_id,
                    "origin_type": ev.source.origin_type,
                    "origin_locator": ev.source.origin_locator,
                    "content_hash": ev.source.content_hash,
                    "parent_source_id": ev.source.parent_source_id,
                    "polarity": ev.polarity,
                }
            }
            self._add(ev.content, metadata)
            report["memories"] += 1

        park = {
            EWP_META_KEY: {
                "kind": "ewp_parked",
                "proposition_id": view.proposition_id,
                "checks": [{**c.__dict__, "source": c.source.__dict__} for c in view.checks],
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
            }
        }
        self._add(f"ewp-parked:{view.proposition_id}", park)
        report["checks_parked"] = len(view.checks)
        report["conflicts_parked"] = len(view.conflicts)
        return report

    def _add(self, text: str, metadata: dict[str, Any]) -> Any:
        messages = [{"role": "user", "content": text}]
        kwargs = {**self._scope(), "metadata": metadata, "infer": self.infer}
        return self._call("add", messages, **kwargs)
