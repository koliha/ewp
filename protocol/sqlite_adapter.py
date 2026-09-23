"""Minimal SQLite evidence store. Assertions are stored; warrant is never written back.

Every record is partitioned by proposition_id. Evidence-bearing records
(sources, assertions, evidence, checks) are append-only: writing an existing
id with different content is refused, never replaced. Conflict participants
are fixed at first write; only status and note may change. View
completeness metadata is one row per proposition.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from typing import Any

from .classify import validate_view
from .types import (
    Assertion,
    Conflict,
    EvidenceItem,
    EvidenceView,
    LineageEdge,
    SourceRef,
    VerificationCheck,
)

SCHEMA_VERSION = 2

SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
  proposition_id TEXT NOT NULL,
  source_id TEXT NOT NULL,
  lineage_id TEXT NOT NULL,
  origin_type TEXT NOT NULL,
  origin_locator TEXT NOT NULL,
  snapshot_id TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  observed_at TEXT NOT NULL,
  extractor_id TEXT,
  parent_source_id TEXT,
  PRIMARY KEY (proposition_id, source_id)
);
CREATE TABLE IF NOT EXISTS assertions (
  proposition_id TEXT NOT NULL,
  assertion_id TEXT NOT NULL,
  text TEXT NOT NULL,
  asserted_by TEXT NOT NULL,
  assertion_confidence REAL NOT NULL,
  source_id TEXT NOT NULL,
  asserted_at TEXT NOT NULL,
  PRIMARY KEY (proposition_id, assertion_id)
);
CREATE TABLE IF NOT EXISTS evidence (
  proposition_id TEXT NOT NULL,
  evidence_id TEXT NOT NULL,
  polarity TEXT NOT NULL,
  source_id TEXT NOT NULL,
  content TEXT NOT NULL,
  observed_at TEXT NOT NULL,
  PRIMARY KEY (proposition_id, evidence_id)
);
CREATE TABLE IF NOT EXISTS checks (
  proposition_id TEXT NOT NULL,
  check_id TEXT NOT NULL,
  method TEXT NOT NULL,
  scope TEXT NOT NULL,
  source_id TEXT NOT NULL,
  observed_at TEXT NOT NULL,
  result TEXT NOT NULL,
  subjects TEXT NOT NULL,
  PRIMARY KEY (proposition_id, check_id)
);
CREATE TABLE IF NOT EXISTS views (
  proposition_id TEXT PRIMARY KEY,
  view_id TEXT NOT NULL,
  omitted_sources TEXT NOT NULL,
  retrieval_scope TEXT NOT NULL,
  degraded INTEGER NOT NULL,
  freshness_policy_seconds INTEGER NOT NULL,
  subjects TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS conflicts (
  conflict_id TEXT PRIMARY KEY,
  proposition_ids TEXT NOT NULL,
  status TEXT NOT NULL,
  note TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS lineage (
  from_id TEXT NOT NULL,
  to_id TEXT NOT NULL,
  kind TEXT NOT NULL,
  UNIQUE (from_id, to_id, kind)
);
"""


class ImmutableRecordError(ValueError):
    """An append-only record id was re-written with different content."""


def _pid_json(ids) -> str:
    return json.dumps(sorted(ids))


class SQLiteAdapter:
    def __init__(self, path: str = ":memory:") -> None:
        self._lock = threading.Lock()
        self.conn = sqlite3.connect(path, check_same_thread=False, timeout=5)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA busy_timeout=5000")
        version = self.conn.execute("PRAGMA user_version").fetchone()[0]
        has_tables = self.conn.execute(
            "SELECT count(*) FROM sqlite_master WHERE type='table'"
        ).fetchone()[0]
        if has_tables and version != SCHEMA_VERSION:
            raise RuntimeError(
                f"{path}: SQLite schema version {version}, expected {SCHEMA_VERSION}. "
                "This database predates EWP-0.2.0; re-ingest into a new file."
            )
        self.conn.executescript(SCHEMA)
        self.conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
        self.conn.commit()

    # -- writes -----------------------------------------------------------

    def _put_immutable(self, table: str, key: dict[str, Any], row: dict[str, Any]) -> None:
        where = " AND ".join(f"{k}=?" for k in key)
        existing = self.conn.execute(
            f"SELECT * FROM {table} WHERE {where}", tuple(key.values())
        ).fetchone()
        full = {**key, **row}
        if existing is None:
            cols = ", ".join(full)
            marks = ", ".join("?" for _ in full)
            self.conn.execute(f"INSERT INTO {table} ({cols}) VALUES ({marks})", tuple(full.values()))
            return
        for col, value in full.items():
            if existing[col] != value:
                raise ImmutableRecordError(
                    f"{table} {tuple(key.values())} is append-only; "
                    f"{col} {existing[col]!r} != {value!r}"
                )

    def _put_source(self, proposition_id: str, s: SourceRef) -> None:
        self._put_immutable(
            "sources",
            {"proposition_id": proposition_id, "source_id": s.source_id},
            {
                "lineage_id": s.lineage_id,
                "origin_type": s.origin_type,
                "origin_locator": s.origin_locator,
                "snapshot_id": s.snapshot_id,
                "content_hash": s.content_hash,
                "observed_at": s.observed_at,
                "extractor_id": s.extractor_id,
                "parent_source_id": s.parent_source_id,
            },
        )

    def _put_conflict(self, c: Conflict) -> None:
        participants = _pid_json(c.proposition_ids)
        existing = self.conn.execute(
            "SELECT proposition_ids FROM conflicts WHERE conflict_id=?", (c.conflict_id,)
        ).fetchone()
        if existing is not None and _pid_json(json.loads(existing["proposition_ids"])) != participants:
            raise ImmutableRecordError(
                f"conflict {c.conflict_id} participants are fixed: "
                f"{existing['proposition_ids']} != {participants}"
            )
        self.conn.execute(
            """INSERT INTO conflicts VALUES (?,?,?,?)
               ON CONFLICT(conflict_id) DO UPDATE SET status=excluded.status, note=excluded.note""",
            (c.conflict_id, participants, c.status, c.note),
        )

    def load_view(self, view: EvidenceView) -> None:
        validate_view(view)
        with self._lock:
            try:
                self._load_view_unlocked(view)
                self.conn.commit()
            except Exception:
                self.conn.rollback()
                raise

    def _load_view_unlocked(self, view: EvidenceView) -> None:
        for a in view.assertions:
            self._put_source(a.proposition_id, a.source)
            self._put_immutable(
                "assertions",
                {"proposition_id": a.proposition_id, "assertion_id": a.assertion_id},
                {
                    "text": a.text,
                    "asserted_by": a.asserted_by,
                    "assertion_confidence": a.assertion_confidence,
                    "source_id": a.source.source_id,
                    "asserted_at": a.asserted_at,
                },
            )
        for e in view.evidence:
            self._put_source(e.proposition_id, e.source)
            self._put_immutable(
                "evidence",
                {"proposition_id": e.proposition_id, "evidence_id": e.evidence_id},
                {
                    "polarity": e.polarity,
                    "source_id": e.source.source_id,
                    "content": e.content,
                    "observed_at": e.observed_at,
                },
            )
        for c in view.checks:
            self._put_source(view.proposition_id, c.source)
            self._put_immutable(
                "checks",
                {"proposition_id": view.proposition_id, "check_id": c.check_id},
                {
                    "method": c.method,
                    "scope": c.scope,
                    "source_id": c.source.source_id,
                    "observed_at": c.observed_at,
                    "result": c.result,
                    "subjects": json.dumps(list(c.subjects)),
                },
            )
        for c in view.conflicts:
            self._put_conflict(c)
        for e in view.lineage:
            self.conn.execute("INSERT OR IGNORE INTO lineage VALUES (?,?,?)", (e.from_id, e.to_id, e.kind))
        self.conn.execute(
            "INSERT OR REPLACE INTO views VALUES (?,?,?,?,?,?,?)",
            (
                view.proposition_id,
                view.view_id,
                json.dumps(list(view.omitted_sources)),
                view.retrieval_scope,
                1 if view.degraded else 0,
                view.freshness_policy_seconds,
                json.dumps(list(view.subjects)),
            ),
        )

    # -- reads ------------------------------------------------------------

    def _source(self, proposition_id: str, source_id: str) -> SourceRef:
        r = self.conn.execute(
            "SELECT * FROM sources WHERE proposition_id=? AND source_id=?",
            (proposition_id, source_id),
        ).fetchone()
        return SourceRef(
            source_id=r["source_id"],
            lineage_id=r["lineage_id"],
            origin_type=r["origin_type"],
            origin_locator=r["origin_locator"],
            snapshot_id=r["snapshot_id"],
            content_hash=r["content_hash"],
            observed_at=r["observed_at"],
            extractor_id=r["extractor_id"],
            parent_source_id=r["parent_source_id"],
        )

    def get_view(
        self,
        proposition_id: str,
        view_id: str,
        *,
        omitted_sources: list[str] | None = None,
        retrieval_scope: str | None = None,
        degraded: bool | None = None,
        freshness_policy_seconds: int | None = None,
    ) -> EvidenceView:
        with self._lock:
            return self._get_view_unlocked(
                proposition_id,
                view_id,
                omitted_sources=omitted_sources,
                retrieval_scope=retrieval_scope,
                degraded=degraded,
                freshness_policy_seconds=freshness_policy_seconds,
            )

    def _get_view_unlocked(
        self,
        proposition_id: str,
        view_id: str,
        *,
        omitted_sources: list[str] | None = None,
        retrieval_scope: str | None = None,
        degraded: bool | None = None,
        freshness_policy_seconds: int | None = None,
    ) -> EvidenceView:
        assertions = [
            Assertion(
                assertion_id=r["assertion_id"],
                proposition_id=r["proposition_id"],
                text=r["text"],
                asserted_by=r["asserted_by"],
                assertion_confidence=r["assertion_confidence"],
                source=self._source(proposition_id, r["source_id"]),
                asserted_at=r["asserted_at"],
            )
            for r in self.conn.execute(
                "SELECT * FROM assertions WHERE proposition_id=? ORDER BY rowid", (proposition_id,)
            )
        ]
        evidence = [
            EvidenceItem(
                evidence_id=r["evidence_id"],
                proposition_id=r["proposition_id"],
                polarity=r["polarity"],
                source=self._source(proposition_id, r["source_id"]),
                content=r["content"],
                observed_at=r["observed_at"],
            )
            for r in self.conn.execute(
                "SELECT * FROM evidence WHERE proposition_id=? ORDER BY rowid", (proposition_id,)
            )
        ]
        checks = [
            VerificationCheck(
                check_id=r["check_id"],
                method=r["method"],
                scope=r["scope"],
                source=self._source(proposition_id, r["source_id"]),
                observed_at=r["observed_at"],
                result=r["result"],
                subjects=tuple(json.loads(r["subjects"])),
            )
            for r in self.conn.execute(
                "SELECT * FROM checks WHERE proposition_id=? ORDER BY rowid", (proposition_id,)
            )
        ]
        conflicts = [
            Conflict(
                conflict_id=r["conflict_id"],
                proposition_ids=tuple(json.loads(r["proposition_ids"])),
                status=r["status"],
                note=r["note"],
            )
            for r in self.conn.execute("SELECT * FROM conflicts ORDER BY rowid")
            if proposition_id in json.loads(r["proposition_ids"])
        ]
        lineage = [
            LineageEdge(from_id=r["from_id"], to_id=r["to_id"], kind=r["kind"])
            for r in self.conn.execute("SELECT * FROM lineage ORDER BY rowid")
            if r["from_id"] == proposition_id
            or r["to_id"] == proposition_id
            or r["from_id"].startswith(proposition_id + ":")
            or r["to_id"].startswith(proposition_id + ":")
        ]
        meta = self.conn.execute(
            "SELECT * FROM views WHERE proposition_id=?", (proposition_id,)
        ).fetchone()
        if meta is None:
            # No completeness record: the store cannot vouch for this view.
            stored_view_id = "sqlite"
            stored_omitted: list[str] = []
            stored_scope = "unknown"
            stored_degraded = True
            stored_fresh = 86400 * 30
            stored_subjects: tuple[str, ...] = ()
        else:
            stored_view_id = meta["view_id"]
            stored_omitted = json.loads(meta["omitted_sources"])
            stored_scope = meta["retrieval_scope"]
            stored_degraded = bool(meta["degraded"])
            stored_fresh = int(meta["freshness_policy_seconds"])
            stored_subjects = tuple(json.loads(meta["subjects"]))
        return EvidenceView(
            view_id=view_id or stored_view_id,
            proposition_id=proposition_id,
            assertions=assertions,
            evidence=evidence,
            lineage=lineage,
            conflicts=conflicts,
            checks=checks,
            omitted_sources=stored_omitted if omitted_sources is None else omitted_sources,
            retrieval_scope=stored_scope if retrieval_scope is None else retrieval_scope,
            degraded=stored_degraded if degraded is None else degraded,
            freshness_policy_seconds=stored_fresh if freshness_policy_seconds is None else freshness_policy_seconds,
            subjects=stored_subjects,
        )
