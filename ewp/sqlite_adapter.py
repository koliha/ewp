"""Minimal SQLite evidence store. Assertions are stored; warrant is never written back.

Two layers:

* Ledger. Sources, assertions, evidence, and checks are partitioned by the
  owning proposition and are append-only: writing an existing id with
  different content is refused, never replaced.
* Views. Each (proposition_id, view_id) is an immutable snapshot: an explicit
  membership list of ledger records plus that view's conflicts, lineage,
  completeness, freshness, and subjects. Re-writing an identical snapshot is
  a no-op; changing one is refused. `get_view(pid, view_id)` returns exactly
  that snapshot; `get_view(pid)` returns the latest.

Every id is proposition-local, including conflict_id. A conflict's
participants are fixed at first sight across that proposition's views; its
status and note belong to each snapshot, so resolving a conflict is a new view.

Writes run in `BEGIN IMMEDIATE` transactions, so a read-then-write (extend_view)
is atomic across processes sharing the file, not only across threads.
`read_only=True` opens an existing ledger with SQLite's read-only mode and
refuses a path that does not exist.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any, Iterable

from .classify import validate_view
from .codec import content_view_id
from .types import (
    Assertion,
    Conflict,
    EvidenceItem,
    EvidenceView,
    LineageEdge,
    SourceRef,
    VerificationCheck,
)

SCHEMA_VERSION = 4

SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
  owner TEXT NOT NULL,
  source_id TEXT NOT NULL,
  lineage_id TEXT NOT NULL,
  origin_type TEXT NOT NULL,
  origin_locator TEXT NOT NULL,
  snapshot_id TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  observed_at TEXT NOT NULL,
  extractor_id TEXT,
  parent_source_id TEXT,
  PRIMARY KEY (owner, source_id)
);
CREATE TABLE IF NOT EXISTS assertions (
  owner TEXT NOT NULL,
  assertion_id TEXT NOT NULL,
  proposition_id TEXT NOT NULL,
  text TEXT NOT NULL,
  asserted_by TEXT NOT NULL,
  assertion_confidence REAL NOT NULL,
  source_id TEXT NOT NULL,
  asserted_at TEXT NOT NULL,
  PRIMARY KEY (owner, assertion_id)
);
CREATE TABLE IF NOT EXISTS evidence (
  owner TEXT NOT NULL,
  evidence_id TEXT NOT NULL,
  proposition_id TEXT NOT NULL,
  polarity TEXT NOT NULL,
  source_id TEXT NOT NULL,
  content TEXT NOT NULL,
  observed_at TEXT NOT NULL,
  PRIMARY KEY (owner, evidence_id)
);
CREATE TABLE IF NOT EXISTS checks (
  owner TEXT NOT NULL,
  check_id TEXT NOT NULL,
  method TEXT NOT NULL,
  scope TEXT NOT NULL,
  source_id TEXT NOT NULL,
  observed_at TEXT NOT NULL,
  result TEXT NOT NULL,
  subjects TEXT NOT NULL,
  PRIMARY KEY (owner, check_id)
);
CREATE TABLE IF NOT EXISTS conflict_participants (
  owner TEXT NOT NULL,
  conflict_id TEXT NOT NULL,
  proposition_ids TEXT NOT NULL,
  PRIMARY KEY (owner, conflict_id)
);
CREATE TABLE IF NOT EXISTS views (
  seq INTEGER PRIMARY KEY AUTOINCREMENT,
  owner TEXT NOT NULL,
  view_id TEXT NOT NULL,
  digest TEXT NOT NULL,
  omitted_sources TEXT NOT NULL,
  retrieval_scope TEXT NOT NULL,
  degraded INTEGER NOT NULL,
  freshness_policy_seconds INTEGER NOT NULL,
  subjects TEXT NOT NULL,
  UNIQUE (owner, view_id)
);
CREATE TABLE IF NOT EXISTS view_members (
  owner TEXT NOT NULL,
  view_id TEXT NOT NULL,
  ord INTEGER NOT NULL,
  kind TEXT NOT NULL,
  ref TEXT NOT NULL,
  PRIMARY KEY (owner, view_id, ord)
);
"""


class ImmutableRecordError(ValueError):
    """An append-only record or view snapshot was re-written with different content."""


class MissingViewError(KeyError):
    """No stored view for that proposition (or that view_id)."""


def _pid_json(ids: Iterable[str]) -> str:
    return json.dumps(sorted(ids))


class LedgerError(RuntimeError):
    """The ledger file cannot be used: missing (read-only), or an older schema."""


class SQLiteAdapter:
    def __init__(self, path: str = ":memory:", *, read_only: bool = False) -> None:
        self._lock = threading.Lock()
        self.read_only = read_only
        if read_only:
            if path == ":memory:":
                raise LedgerError("a read-only ledger needs a file path")
            file = Path(path).resolve()
            if not file.is_file():
                raise LedgerError(
                    f"ledger not found: {file}. The read-only server opens an existing ledger; "
                    "create one with ewp-ingest, and check the --db path."
                )
            target, uri = file.as_uri() + "?mode=ro", True
        else:
            target, uri = path, False
        # Autocommit mode: transactions are explicit BEGIN IMMEDIATE ... COMMIT.
        self.conn = sqlite3.connect(target, check_same_thread=False, timeout=5, isolation_level=None, uri=uri)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA busy_timeout=5000")
        version = self.conn.execute("PRAGMA user_version").fetchone()[0]
        has_tables = self.conn.execute(
            "SELECT count(*) FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchone()[0]
        if has_tables and version != SCHEMA_VERSION:
            self.conn.close()
            raise LedgerError(
                f"{path}: ledger schema version {version}, expected {SCHEMA_VERSION}. "
                "It was created by an earlier development build of EWP; start a new --db file and re-ingest."
            )
        if read_only:
            if not has_tables:
                self.conn.close()
                raise LedgerError(f"{path} is not an EWP ledger (no tables); create it with ewp-ingest")
            return
        self.conn.executescript(SCHEMA)
        self.conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")

    def close(self) -> None:
        with self._lock:
            self.conn.close()

    def __enter__(self) -> "SQLiteAdapter":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- ledger writes ----------------------------------------------------

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

    def _put_source(self, owner: str, s: SourceRef) -> None:
        self._put_immutable(
            "sources",
            {"owner": owner, "source_id": s.source_id},
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

    def _fix_participants(self, owner: str, c: Conflict) -> None:
        participants = _pid_json(c.proposition_ids)
        existing = self.conn.execute(
            "SELECT proposition_ids FROM conflict_participants WHERE owner=? AND conflict_id=?",
            (owner, c.conflict_id),
        ).fetchone()
        if existing is None:
            self.conn.execute("INSERT INTO conflict_participants VALUES (?,?,?)", (owner, c.conflict_id, participants))
        elif existing["proposition_ids"] != participants:
            raise ImmutableRecordError(
                f"conflict {c.conflict_id} participants are fixed: "
                f"{existing['proposition_ids']} != {participants}"
            )

    # -- view writes ------------------------------------------------------

    def _begin(self) -> None:
        if self.read_only:
            raise LedgerError("this ledger is open read-only")
        self.conn.execute("BEGIN IMMEDIATE")

    def load_view(self, view: EvidenceView) -> None:
        """Store `view` as the immutable snapshot (proposition_id, view_id)."""
        validate_view(view)
        with self._lock:
            self._begin()
            try:
                self._store_view(view)
                self.conn.execute("COMMIT")
            except Exception:
                self.conn.execute("ROLLBACK")
                raise

    def extend_view(
        self,
        proposition_id: str,
        *,
        assertions: Iterable[Assertion] = (),
        evidence: Iterable[EvidenceItem] = (),
        checks: Iterable[VerificationCheck] = (),
        new_view_id: str | None = None,
    ) -> EvidenceView:
        """Atomically create a new snapshot: the latest view plus these records.

        Read and write happen under one lock and one transaction, so two
        concurrent appends cannot drop each other's records from "latest".
        """
        with self._lock:
            self._begin()
            try:
                base = self._get_view_unlocked(proposition_id, None)
                view = EvidenceView(
                    view_id="",
                    proposition_id=proposition_id,
                    assertions=base.assertions + list(assertions),
                    evidence=base.evidence + list(evidence),
                    lineage=base.lineage,
                    conflicts=base.conflicts,
                    checks=base.checks + list(checks),
                    omitted_sources=base.omitted_sources,
                    retrieval_scope=base.retrieval_scope,
                    degraded=base.degraded,
                    freshness_policy_seconds=base.freshness_policy_seconds,
                    subjects=base.subjects,
                )
                validate_view(view)
                view.view_id = new_view_id or content_view_id(view)
                self._store_view(view)
                self.conn.execute("COMMIT")
                return view
            except Exception:
                self.conn.execute("ROLLBACK")
                raise

    def _store_view(self, view: EvidenceView) -> None:
        owner = view.proposition_id
        digest = content_view_id(view)
        existing = self.conn.execute(
            "SELECT digest FROM views WHERE owner=? AND view_id=?", (owner, view.view_id)
        ).fetchone()
        if existing is not None:
            if existing["digest"] != digest:
                raise ImmutableRecordError(
                    f"view {view.view_id!r} of {owner!r} is an immutable snapshot with different content; "
                    "store the new evidence under a new view_id"
                )
            return

        members: list[tuple[str, str]] = []
        for a in view.assertions:
            self._put_source(owner, a.source)
            self._put_immutable(
                "assertions",
                {"owner": owner, "assertion_id": a.assertion_id},
                {
                    "proposition_id": a.proposition_id,
                    "text": a.text,
                    "asserted_by": a.asserted_by,
                    "assertion_confidence": a.assertion_confidence,
                    "source_id": a.source.source_id,
                    "asserted_at": a.asserted_at,
                },
            )
            members.append(("assertion", a.assertion_id))
        for e in view.evidence:
            self._put_source(owner, e.source)
            self._put_immutable(
                "evidence",
                {"owner": owner, "evidence_id": e.evidence_id},
                {
                    "proposition_id": e.proposition_id,
                    "polarity": e.polarity,
                    "source_id": e.source.source_id,
                    "content": e.content,
                    "observed_at": e.observed_at,
                },
            )
            members.append(("evidence", e.evidence_id))
        for c in view.checks:
            self._put_source(owner, c.source)
            self._put_immutable(
                "checks",
                {"owner": owner, "check_id": c.check_id},
                {
                    "method": c.method,
                    "scope": c.scope,
                    "source_id": c.source.source_id,
                    "observed_at": c.observed_at,
                    "result": c.result,
                    "subjects": json.dumps(sorted(c.subjects)),  # a set: order is not content
                },
            )
            members.append(("check", c.check_id))
        for c in view.conflicts:
            self._fix_participants(owner, c)
            members.append(("conflict", json.dumps(
                {"conflict_id": c.conflict_id, "proposition_ids": list(c.proposition_ids), "status": c.status, "note": c.note}
            )))
        for edge in view.lineage:
            members.append(("lineage", json.dumps({"from_id": edge.from_id, "to_id": edge.to_id, "kind": edge.kind})))

        self.conn.execute(
            """INSERT INTO views (owner, view_id, digest, omitted_sources, retrieval_scope,
                                  degraded, freshness_policy_seconds, subjects)
               VALUES (?,?,?,?,?,?,?,?)""",
            (
                owner,
                view.view_id,
                digest,
                json.dumps(list(view.omitted_sources)),
                view.retrieval_scope,
                1 if view.degraded else 0,
                view.freshness_policy_seconds,
                json.dumps(list(view.subjects)),
            ),
        )
        self.conn.executemany(
            "INSERT INTO view_members VALUES (?,?,?,?,?)",
            [(owner, view.view_id, i, kind, ref) for i, (kind, ref) in enumerate(members)],
        )

    # -- reads ------------------------------------------------------------

    def list_propositions(self, query: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        """Propositions with their latest snapshot id and assertion texts.

        `query` is a case-insensitive substring match on the proposition id or
        any assertion text in the latest snapshot. Discovery only: it says what
        exists, not what is warranted.
        """
        needle = (query or "").lower()
        out: list[dict[str, Any]] = []
        with self._lock:
            owners = [
                r["owner"]
                for r in self.conn.execute("SELECT owner, MAX(seq) AS s FROM views GROUP BY owner ORDER BY s DESC")
            ]
            for owner in owners:
                view = self._get_view_unlocked(owner, None)
                texts = list(dict.fromkeys(a.text for a in view.assertions))
                if needle and needle not in owner.lower() and not any(needle in t.lower() for t in texts):
                    continue
                out.append({
                    "proposition_id": owner,
                    "latest_view_id": view.view_id,
                    "assertions": texts[:5],
                    "snapshots": self.conn.execute("SELECT count(*) FROM views WHERE owner=?", (owner,)).fetchone()[0],
                })
                if len(out) >= limit:
                    break
        return out

    def view_ids(self, proposition_id: str) -> list[str]:
        """Snapshot ids for a proposition, oldest first."""
        with self._lock:
            return [
                r["view_id"]
                for r in self.conn.execute("SELECT view_id FROM views WHERE owner=? ORDER BY seq", (proposition_id,))
            ]

    def _source(self, owner: str, source_id: str) -> SourceRef:
        r = self.conn.execute(
            "SELECT * FROM sources WHERE owner=? AND source_id=?", (owner, source_id)
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
        view_id: str | None = None,
        *,
        omitted_sources: list[str] | None = None,
        retrieval_scope: str | None = None,
        degraded: bool | None = None,
        freshness_policy_seconds: int | None = None,
    ) -> EvidenceView:
        """Exactly the stored snapshot; the latest one when view_id is None.

        Raises MissingViewError when nothing is stored. Keyword overrides
        replace completeness metadata on the returned object only.
        """
        with self._lock:
            view = self._get_view_unlocked(proposition_id, view_id)
        if omitted_sources is not None:
            view.omitted_sources = omitted_sources
        if retrieval_scope is not None:
            view.retrieval_scope = retrieval_scope
        if degraded is not None:
            view.degraded = degraded
        if freshness_policy_seconds is not None:
            view.freshness_policy_seconds = freshness_policy_seconds
        return view

    def _get_view_unlocked(self, owner: str, view_id: str | None) -> EvidenceView:
        if view_id is None:
            meta = self.conn.execute(
                "SELECT * FROM views WHERE owner=? ORDER BY seq DESC LIMIT 1", (owner,)
            ).fetchone()
        else:
            meta = self.conn.execute(
                "SELECT * FROM views WHERE owner=? AND view_id=?", (owner, view_id)
            ).fetchone()
        if meta is None:
            raise MissingViewError(f"no stored view for {owner!r}" + (f" with view_id {view_id!r}" if view_id else ""))

        assertions: list[Assertion] = []
        evidence: list[EvidenceItem] = []
        checks: list[VerificationCheck] = []
        conflicts: list[Conflict] = []
        lineage: list[LineageEdge] = []
        for m in self.conn.execute(
            "SELECT kind, ref FROM view_members WHERE owner=? AND view_id=? ORDER BY ord",
            (owner, meta["view_id"]),
        ):
            kind, ref = m["kind"], m["ref"]
            if kind == "assertion":
                r = self.conn.execute("SELECT * FROM assertions WHERE owner=? AND assertion_id=?", (owner, ref)).fetchone()
                assertions.append(Assertion(
                    assertion_id=r["assertion_id"],
                    proposition_id=r["proposition_id"],
                    text=r["text"],
                    asserted_by=r["asserted_by"],
                    assertion_confidence=r["assertion_confidence"],
                    source=self._source(owner, r["source_id"]),
                    asserted_at=r["asserted_at"],
                ))
            elif kind == "evidence":
                r = self.conn.execute("SELECT * FROM evidence WHERE owner=? AND evidence_id=?", (owner, ref)).fetchone()
                evidence.append(EvidenceItem(
                    evidence_id=r["evidence_id"],
                    proposition_id=r["proposition_id"],
                    polarity=r["polarity"],
                    source=self._source(owner, r["source_id"]),
                    content=r["content"],
                    observed_at=r["observed_at"],
                ))
            elif kind == "check":
                r = self.conn.execute("SELECT * FROM checks WHERE owner=? AND check_id=?", (owner, ref)).fetchone()
                checks.append(VerificationCheck(
                    check_id=r["check_id"],
                    method=r["method"],
                    scope=r["scope"],
                    source=self._source(owner, r["source_id"]),
                    observed_at=r["observed_at"],
                    result=r["result"],
                    subjects=tuple(json.loads(r["subjects"])),
                ))
            elif kind == "conflict":
                c = json.loads(ref)
                conflicts.append(Conflict(c["conflict_id"], tuple(c["proposition_ids"]), c["status"], c["note"]))
            elif kind == "lineage":
                e = json.loads(ref)
                lineage.append(LineageEdge(e["from_id"], e["to_id"], e["kind"]))

        return EvidenceView(
            view_id=meta["view_id"],
            proposition_id=owner,
            assertions=assertions,
            evidence=evidence,
            lineage=lineage,
            conflicts=conflicts,
            checks=checks,
            omitted_sources=json.loads(meta["omitted_sources"]),
            retrieval_scope=meta["retrieval_scope"],
            degraded=bool(meta["degraded"]),
            freshness_policy_seconds=int(meta["freshness_policy_seconds"]),
            subjects=tuple(json.loads(meta["subjects"])),
        )
