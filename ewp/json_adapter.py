"""Directory-of-JSON evidence store.

Deliberately does *not* mirror the SQLite schema. Propositions nest
observations, verification_history, and a source_graph. The adapter's
only job is to flatten that into EvidenceView.

Same snapshot contract as SQLite: each (proposition_id, view_id) is an
immutable document; `get_view(pid)` returns the latest. Directory and file
names are hashes of the ids, so no id can collide with another or escape
the store root. Every document records its own ids and is checked on read.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any

from .classify import validate_view
from .codec import canonical_dict, record_identity_conflicts
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


def _src(d: dict[str, Any]) -> SourceRef:
    return SourceRef(
        source_id=d["source_id"],
        lineage_id=d["lineage_id"],
        origin_type=d["origin_type"],
        origin_locator=d["origin_locator"],
        snapshot_id=d["snapshot_id"],
        content_hash=d["content_hash"],
        observed_at=d["observed_at"],
        extractor_id=d.get("extractor_id"),
        parent_source_id=d.get("parent_source_id"),
    )


def _key(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:32]


def _shared(action, what: Path):
    """Run a file operation, retrying briefly while Windows reports a sharing
    conflict: os.replace fails while any process (another EWP reader, a virus
    scanner) has the target open, and an open can fail mid-replace. POSIX
    does not raise this for a sharing conflict."""
    deadline = time.monotonic() + 5.0
    while True:
        try:
            return action()
        except PermissionError as exc:
            if time.monotonic() > deadline:
                raise LedgerError(f"JSON store busy: {what} stayed locked by another process ({exc})") from exc
            time.sleep(0.005)


def _read_json(path: Path):
    return json.loads(_shared(lambda: path.read_text(encoding="utf-8"), path))


def _write_atomic(path: Path, text: str) -> None:
    """Write a temp file next to `path`, then replace: a reader or a retry sees
    the old file or the whole new one, never a partial write."""
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    _shared(lambda: os.replace(tmp, path), path)


@contextlib.contextmanager
def _exclusive(lock_path: Path, timeout_seconds: float):
    """An OS file lock (fcntl on POSIX, msvcrt on Windows). The OS releases it
    when the holder exits, so a crashed writer never leaves a stale lock."""
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o644)
    try:
        if os.name == "nt":
            import msvcrt

            deadline = time.monotonic() + timeout_seconds
            while True:
                try:
                    os.lseek(fd, 0, os.SEEK_SET)
                    msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                    break
                except OSError:
                    if time.monotonic() > deadline:
                        raise LedgerError(f"JSON store busy: could not lock {lock_path} within {timeout_seconds}s")
                    time.sleep(0.01)
            try:
                yield
            finally:
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            deadline = time.monotonic() + timeout_seconds
            while True:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError:
                    if time.monotonic() > deadline:
                        raise LedgerError(f"JSON store busy: could not lock {lock_path} within {timeout_seconds}s")
                    time.sleep(0.01)
            try:
                yield
            finally:
                fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


class JsonFileAdapter:
    def __init__(self, root: str | Path, *, lock_timeout_seconds: float = 30.0) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock_timeout_seconds = lock_timeout_seconds

    def _pdir(self, proposition_id: str) -> Path:
        return self.root / "propositions" / _key(proposition_id)

    def load_view(self, view: EvidenceView) -> None:
        """Persist using a nested document shape, not SQLite tables."""
        validate_view(view)
        doc = {
            "claim": view.proposition_id,
            "view_meta": {
                "view_id": view.view_id,
                "freshness_policy_seconds": view.freshness_policy_seconds,
                "retrieval_scope": view.retrieval_scope,
                "degraded": view.degraded,
                "omitted_sources": view.omitted_sources,
                "subjects": list(view.subjects),
            },
            "observations": [
                {
                    "kind": "assertion",
                    "id": a.assertion_id,
                    "about": a.proposition_id,
                    "text": a.text,
                    "asserted_by": a.asserted_by,
                    "how_sure_they_sounded": a.assertion_confidence,
                    "when": a.asserted_at,
                    "source": a.source.__dict__,
                }
                for a in view.assertions
            ]
            + [
                {
                    "kind": "snippet",
                    "id": e.evidence_id,
                    "about": e.proposition_id,
                    "side": e.polarity,
                    "content": e.content,
                    "when": e.observed_at,
                    "source": e.source.__dict__,
                }
                for e in view.evidence
            ],
            "verification_history": [
                {
                    "id": c.check_id,
                    "how": c.method,
                    "what_was_inspected": c.scope,
                    "when": c.observed_at,
                    "outcome": c.result,
                    "subjects": list(c.subjects),
                    "source": c.source.__dict__,
                }
                for c in view.checks
            ],
            "disputes": [
                {"id": c.conflict_id, "about": list(c.proposition_ids), "state": c.status, "note": c.note}
                for c in view.conflicts
            ],
            "source_graph": [
                {"from": e.from_id, "to": e.to_id, "rel": e.kind} for e in view.lineage
            ],
        }
        body = json.dumps(doc, indent=2, sort_keys=True)
        pdir = self._pdir(view.proposition_id)
        pdir.mkdir(parents=True, exist_ok=True)
        # Check, write, and append to latest.json as one step: without the
        # lock two writers both pass the identity check and one view_id
        # disappears from the history.
        with _exclusive(pdir / ".lock", self.lock_timeout_seconds):
            self._store(view, pdir, body)

    def _store(self, view: EvidenceView, pdir: Path, body: str) -> None:
        """Commit order: the snapshot file (atomically), then its view_id in
        latest.json (atomically). A snapshot is committed once it is in the
        history; a file whose view_id is not there was left by an interrupted
        write and is replaced by the retry."""
        path = pdir / "views" / f"{_key(view.view_id)}.json"
        history = self.view_ids(view.proposition_id)
        if view.view_id in history:
            # Committed: immutable. An identical re-put (in any record order)
            # is a no-op; different content is refused.
            try:
                existing = self._read(view.proposition_id, view.view_id)
            except (ValueError, KeyError, TypeError) as exc:
                raise LedgerError(
                    f"committed snapshot {view.view_id!r} of {view.proposition_id!r} is unreadable ({exc}); "
                    f"the store is damaged: {path}"
                ) from exc
            if canonical_dict(existing) != canonical_dict(view):
                raise ImmutableRecordError(
                    f"view {view.view_id!r} of {view.proposition_id!r} is an immutable snapshot with different content"
                )
            return
        # Not committed. A file at this path is an orphan of an interrupted
        # write (partial, identical, or different): it is not a snapshot, so
        # it is replaced. Record ids are checked against the committed
        # snapshots first, as for any commit.
        stored = [self.get_view(view.proposition_id, vid) for vid in history]
        clashes = record_identity_conflicts(stored, view)
        if clashes:
            raise ImmutableRecordError(
                f"{view.proposition_id!r}: ids already name different records in earlier snapshots: {', '.join(clashes)}"
            )
        path.parent.mkdir(parents=True, exist_ok=True)
        _write_atomic(path, body)
        self._append_history(pdir, view.proposition_id, history, view.view_id)

    @staticmethod
    def _append_history(pdir: Path, proposition_id: str, history: list[str], view_id: str) -> None:
        _write_atomic(pdir / "latest.json", json.dumps({"claim": proposition_id, "view_ids": history + [view_id]}))

    def view_ids(self, proposition_id: str) -> list[str]:
        latest = self._pdir(proposition_id) / "latest.json"
        if not latest.exists():
            return []
        return list(_read_json(latest)["view_ids"])

    def get_view(
        self,
        proposition_id: str,
        view_id: str | None = None,
    ) -> EvidenceView:
        """Exactly a committed snapshot (one in the history); the latest when
        view_id is None. A file an interrupted write left behind is not one."""
        history = self.view_ids(proposition_id)
        if view_id is None:
            if not history:
                raise MissingViewError(f"no stored view for {proposition_id!r}")
            view_id = history[-1]
        elif view_id not in history:
            raise MissingViewError(f"no stored view for {proposition_id!r} with view_id {view_id!r}")
        return self._read(proposition_id, view_id)

    def _read(self, proposition_id: str, view_id: str) -> EvidenceView:
        pdir = self._pdir(proposition_id)
        path = pdir / "views" / f"{_key(view_id)}.json"
        if not path.exists():
            raise MissingViewError(f"no stored view for {proposition_id!r} with view_id {view_id!r}")
        doc = _read_json(path)
        meta = doc["view_meta"]
        if doc["claim"] != proposition_id or meta["view_id"] != view_id:
            raise ValueError(f"store corruption: {path} holds {doc['claim']!r}/{meta['view_id']!r}")
        assertions: list[Assertion] = []
        evidence: list[EvidenceItem] = []
        for obs in doc.get("observations", []):
            source = _src(obs["source"])
            if obs["kind"] == "assertion":
                assertions.append(
                    Assertion(
                        assertion_id=obs["id"],
                        proposition_id=obs["about"],
                        text=obs["text"],
                        asserted_by=obs["asserted_by"],
                        assertion_confidence=obs["how_sure_they_sounded"],
                        source=source,
                        asserted_at=obs["when"],
                    )
                )
            elif obs["kind"] == "snippet":
                evidence.append(
                    EvidenceItem(
                        evidence_id=obs["id"],
                        proposition_id=obs["about"],
                        polarity=obs["side"],
                        source=source,
                        content=obs["content"],
                        observed_at=obs["when"],
                    )
                )
        checks = [
            VerificationCheck(
                check_id=v["id"],
                method=v["how"],
                scope=v["what_was_inspected"],
                source=_src(v["source"]),
                observed_at=v["when"],
                result=v["outcome"],
                subjects=tuple(v["subjects"]),
            )
            for v in doc.get("verification_history", [])
        ]
        conflicts = [
            Conflict(conflict_id=d["id"], proposition_ids=tuple(d["about"]), status=d["state"], note=d.get("note", ""))
            for d in doc.get("disputes", [])
        ]
        lineage = [
            LineageEdge(from_id=e["from"], to_id=e["to"], kind=e["rel"])
            for e in doc.get("source_graph", [])
        ]
        view = EvidenceView(
            view_id=view_id,
            proposition_id=proposition_id,
            assertions=assertions,
            evidence=evidence,
            lineage=lineage,
            conflicts=conflicts,
            checks=checks,
            omitted_sources=meta["omitted_sources"],
            retrieval_scope=meta["retrieval_scope"],
            degraded=meta["degraded"],
            freshness_policy_seconds=meta["freshness_policy_seconds"],
            subjects=tuple(meta["subjects"]),
        )
        validate_view(view)
        return view
