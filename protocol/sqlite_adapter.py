"""Minimal SQLite evidence store. Assertions are stored; warrant is never written back."""

from __future__ import annotations

import json
import sqlite3

from .types import (
    Assertion,
    Conflict,
    EvidenceItem,
    EvidenceView,
    LineageEdge,
    SourceRef,
    VerificationCheck,
)


SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
  source_id TEXT PRIMARY KEY,
  lineage_id TEXT NOT NULL,
  origin_type TEXT NOT NULL,
  origin_locator TEXT NOT NULL,
  snapshot_id TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  observed_at TEXT NOT NULL,
  extractor_id TEXT,
  parent_source_id TEXT
);
CREATE TABLE IF NOT EXISTS assertions (
  assertion_id TEXT PRIMARY KEY,
  proposition_id TEXT NOT NULL,
  text TEXT NOT NULL,
  asserted_by TEXT NOT NULL,
  assertion_confidence REAL NOT NULL,
  source_id TEXT NOT NULL,
  asserted_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS evidence (
  evidence_id TEXT PRIMARY KEY,
  proposition_id TEXT NOT NULL,
  polarity TEXT NOT NULL,
  source_id TEXT NOT NULL,
  content TEXT NOT NULL,
  observed_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS checks (
  check_id TEXT PRIMARY KEY,
  proposition_id TEXT NOT NULL,
  method TEXT NOT NULL,
  scope TEXT NOT NULL,
  source_id TEXT NOT NULL,
  observed_at TEXT NOT NULL,
  result TEXT NOT NULL,
  subjects TEXT NOT NULL DEFAULT '[]'
);
CREATE TABLE IF NOT EXISTS views (
  view_id TEXT PRIMARY KEY,
  proposition_id TEXT NOT NULL,
  omitted_sources TEXT NOT NULL,
  retrieval_scope TEXT NOT NULL,
  degraded INTEGER NOT NULL,
  freshness_policy_seconds INTEGER NOT NULL,
  subjects TEXT NOT NULL DEFAULT '[]'
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
  kind TEXT NOT NULL
);
"""


class SQLiteAdapter:
    def __init__(self, path: str = ":memory:") -> None:
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def _put_source(self, s: SourceRef) -> None:
        self.conn.execute(
            """INSERT OR REPLACE INTO sources
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                s.source_id,
                s.lineage_id,
                s.origin_type,
                s.origin_locator,
                s.snapshot_id,
                s.content_hash,
                s.observed_at,
                s.extractor_id,
                s.parent_source_id,
            ),
        )

    def load_view(self, view: EvidenceView) -> None:
        for a in view.assertions:
            self._put_source(a.source)
            self.conn.execute(
                "INSERT OR REPLACE INTO assertions VALUES (?,?,?,?,?,?,?)",
                (
                    a.assertion_id,
                    a.proposition_id,
                    a.text,
                    a.asserted_by,
                    a.assertion_confidence,
                    a.source.source_id,
                    a.asserted_at,
                ),
            )
        for e in view.evidence:
            self._put_source(e.source)
            self.conn.execute(
                "INSERT OR REPLACE INTO evidence VALUES (?,?,?,?,?,?)",
                (e.evidence_id, e.proposition_id, e.polarity, e.source.source_id, e.content, e.observed_at),
            )
        for c in view.checks:
            self._put_source(c.source)
            self.conn.execute(
                "INSERT OR REPLACE INTO checks VALUES (?,?,?,?,?,?,?,?)",
                (
                    c.check_id,
                    view.proposition_id,
                    c.method,
                    c.scope,
                    c.source.source_id,
                    c.observed_at,
                    c.result,
                    json.dumps(list(c.subjects)),
                ),
            )
        for c in view.conflicts:
            self.conn.execute(
                "INSERT OR REPLACE INTO conflicts VALUES (?,?,?,?)",
                (c.conflict_id, json.dumps(list(c.proposition_ids)), c.status, c.note),
            )
        for e in view.lineage:
            self.conn.execute("INSERT INTO lineage VALUES (?,?,?)", (e.from_id, e.to_id, e.kind))
        self.conn.execute(
            "INSERT OR REPLACE INTO views VALUES (?,?,?,?,?,?,?)",
            (
                view.view_id,
                view.proposition_id,
                json.dumps(list(view.omitted_sources)),
                view.retrieval_scope,
                1 if view.degraded else 0,
                view.freshness_policy_seconds,
                json.dumps(list(view.subjects)),
            ),
        )
        self.conn.commit()

    def _source(self, source_id: str) -> SourceRef:
        r = self.conn.execute("SELECT * FROM sources WHERE source_id=?", (source_id,)).fetchone()
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
        assertions = [
            Assertion(
                assertion_id=r["assertion_id"],
                proposition_id=r["proposition_id"],
                text=r["text"],
                asserted_by=r["asserted_by"],
                assertion_confidence=r["assertion_confidence"],
                source=self._source(r["source_id"]),
                asserted_at=r["asserted_at"],
            )
            for r in self.conn.execute(
                "SELECT * FROM assertions WHERE proposition_id=?", (proposition_id,)
            )
        ]
        evidence = [
            EvidenceItem(
                evidence_id=r["evidence_id"],
                proposition_id=r["proposition_id"],
                polarity=r["polarity"],
                source=self._source(r["source_id"]),
                content=r["content"],
                observed_at=r["observed_at"],
            )
            for r in self.conn.execute(
                "SELECT * FROM evidence WHERE proposition_id=?", (proposition_id,)
            )
        ]
        checks = [
            VerificationCheck(
                check_id=r["check_id"],
                method=r["method"],
                scope=r["scope"],
                source=self._source(r["source_id"]),
                observed_at=r["observed_at"],
                result=r["result"],
                subjects=tuple(json.loads(r["subjects"])) if "subjects" in r.keys() else (),
            )
            for r in self.conn.execute("SELECT * FROM checks WHERE proposition_id=?", (proposition_id,))
        ]
        conflicts = [
            Conflict(
                conflict_id=r["conflict_id"],
                proposition_ids=tuple(json.loads(r["proposition_ids"])),
                status=r["status"],
                note=r["note"],
            )
            for r in self.conn.execute("SELECT * FROM conflicts")
            if proposition_id in json.loads(r["proposition_ids"])
        ]
        lineage = [
            LineageEdge(from_id=r["from_id"], to_id=r["to_id"], kind=r["kind"])
            for r in self.conn.execute("SELECT * FROM lineage")
            if r["from_id"] == proposition_id
            or r["to_id"] == proposition_id
            or r["from_id"].startswith(proposition_id + ":")
            or r["to_id"].startswith(proposition_id + ":")
        ]
        meta = self.conn.execute(
            "SELECT * FROM views WHERE view_id=? OR proposition_id=?",
            (view_id, proposition_id),
        ).fetchone()
        if meta is None:
            stored_omitted: list[str] = []
            stored_scope = "unknown"
            stored_degraded = True
            stored_fresh = 86400 * 30
            stored_subjects: tuple[str, ...] = ()
        else:
            stored_omitted = json.loads(meta["omitted_sources"])
            stored_scope = meta["retrieval_scope"]
            stored_degraded = bool(meta["degraded"])
            stored_fresh = int(meta["freshness_policy_seconds"])
            stored_subjects = tuple(json.loads(meta["subjects"]))
        return EvidenceView(
            view_id=view_id or (meta["view_id"] if meta else "sqlite"),
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
