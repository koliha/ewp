"""Earlier claim-ledger sketch. Not the EWP v0.1 freeze — see protocol/warrant.py.

Graphiti may discover relationships. Models may propose claims.
Only this module may change epistemic state.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from retrieval import Claim as ScoredClaim
from retrieval import build_packet


ISO = "%Y-%m-%dT%H:%M:%S%z"


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def iso(ts: datetime | None) -> str | None:
    if ts is None:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.isoformat()


def parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


CONFIDENCE_CAPS = {
    ("inference", "none"): 0.40,
    ("inference", "model_introspection"): 0.40,
    ("convention", "none"): 0.50,
    ("procedure", "none"): 0.50,
    ("report", "none"): 0.55,
    ("observation", "tool_observation"): 0.75,
    ("observation", "none"): 0.45,
}

VERIFY_METHODS = {
    "external_clock",
    "tool_observation",
    "human_attestation",
    "independent_reproduction",
    "document_quote",
}


class LedgerError(Exception):
    pass


@dataclass
class Node:
    node_id: str
    lineage_id: str
    branch_id: str
    parent_node_ids: list[str]
    agent_label: str | None
    model_label: str | None


class Ledger:
    def __init__(self, path: str = ":memory:") -> None:
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self._init_schema()

    def _init_schema(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS nodes (
              node_id TEXT PRIMARY KEY,
              lineage_id TEXT NOT NULL,
              branch_id TEXT NOT NULL,
              parent_node_ids TEXT NOT NULL DEFAULT '[]',
              agent_label TEXT,
              model_label TEXT,
              started_at TEXT NOT NULL,
              ended_at TEXT
            );
            CREATE TABLE IF NOT EXISTS events (
              event_id TEXT PRIMARY KEY,
              node_id TEXT NOT NULL,
              kind TEXT NOT NULL,
              recorded_at TEXT NOT NULL,
              occurred_at TEXT,
              occurred_at_source TEXT,
              payload TEXT NOT NULL,
              parent_event_ids TEXT NOT NULL DEFAULT '[]'
            );
            CREATE TABLE IF NOT EXISTS claims (
              claim_id TEXT PRIMARY KEY,
              lineage_id TEXT NOT NULL,
              branch_id TEXT NOT NULL,
              proposition TEXT NOT NULL,
              scope TEXT,
              originating_node TEXT NOT NULL,
              originating_event TEXT,
              parent_claim_ids TEXT NOT NULL DEFAULT '[]',
              claim_type TEXT NOT NULL,
              status TEXT NOT NULL,
              verification_method TEXT NOT NULL DEFAULT 'none',
              last_verified_at TEXT,
              falsification_condition TEXT,
              confidence_basis TEXT NOT NULL,
              confidence REAL NOT NULL,
              learned_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS claim_mutations (
              mutation_id TEXT PRIMARY KEY,
              claim_id TEXT NOT NULL,
              event_id TEXT NOT NULL,
              actor_node TEXT NOT NULL,
              op TEXT NOT NULL,
              confidence_before REAL NOT NULL,
              confidence_after REAL NOT NULL,
              before_status TEXT NOT NULL,
              after_status TEXT NOT NULL,
              recorded_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS contradictions (
              contradiction_id TEXT PRIMARY KEY,
              claim_a TEXT NOT NULL,
              claim_b TEXT NOT NULL,
              status TEXT NOT NULL DEFAULT 'open',
              note TEXT,
              created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS evidence_refs (
              claim_id TEXT NOT NULL,
              event_id TEXT NOT NULL
            );
            """
        )
        self.conn.commit()

    def _event(
        self,
        node_id: str,
        kind: str,
        payload: dict[str, Any],
        occurred_at: str | None = None,
        occurred_at_source: str | None = None,
    ) -> str:
        event_id = str(uuid.uuid4())
        self.conn.execute(
            """INSERT INTO events
               (event_id, node_id, kind, recorded_at, occurred_at, occurred_at_source, payload)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                event_id,
                node_id,
                kind,
                iso(now_utc()),
                occurred_at,
                occurred_at_source,
                json.dumps(payload),
            ),
        )
        return event_id

    def _mutate(
        self,
        claim_id: str,
        event_id: str,
        actor_node: str,
        op: str,
        before: sqlite3.Row,
        after_status: str,
        after_conf: float,
    ) -> None:
        if op != "verify" and after_conf > before["confidence"] + 1e-9:
            raise LedgerError("confidence may not increase except via verify")
        self.conn.execute(
            """INSERT INTO claim_mutations
               (mutation_id, claim_id, event_id, actor_node, op,
                confidence_before, confidence_after, before_status, after_status, recorded_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                str(uuid.uuid4()),
                claim_id,
                event_id,
                actor_node,
                op,
                before["confidence"],
                after_conf,
                before["status"],
                after_status,
                iso(now_utc()),
            ),
        )

    def session_open(
        self,
        lineage_id: str,
        branch_id: str = "main",
        parent_node_ids: list[str] | None = None,
        agent_label: str | None = None,
        model_label: str | None = None,
    ) -> Node:
        node_id = str(uuid.uuid4())
        parents = parent_node_ids or []
        self.conn.execute(
            """INSERT INTO nodes
               (node_id, lineage_id, branch_id, parent_node_ids, agent_label, model_label, started_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                node_id,
                lineage_id,
                branch_id,
                json.dumps(parents),
                agent_label,
                model_label,
                iso(now_utc()),
            ),
        )
        self._event(node_id, "session_open", {"branch_id": branch_id, "parents": parents})
        self.conn.commit()
        return Node(node_id, lineage_id, branch_id, parents, agent_label, model_label)

    def session_close(self, node_id: str, proposed: list[dict[str, Any]] | None = None) -> list[str]:
        self.conn.execute(
            "UPDATE nodes SET ended_at = ? WHERE node_id = ?",
            (iso(now_utc()), node_id),
        )
        self._event(node_id, "session_close", {"proposed_count": len(proposed or [])})
        ids = []
        for draft in proposed or []:
            draft = dict(draft)
            draft.pop("status", None)
            ids.append(self.claim_propose(node_id=node_id, **draft)["claim_id"])
        self.conn.commit()
        return ids

    def clock_check(self, node_id: str, claimed_now: str | None = None) -> dict[str, Any]:
        host = now_utc()
        claimed = parse_ts(claimed_now)
        delta_s = None
        diverge = False
        if claimed is not None:
            delta_s = abs((host - claimed).total_seconds())
            diverge = delta_s > 300
        event_id = self._event(
            node_id,
            "external_check",
            {
                "host_now": iso(host),
                "claimed_now": claimed_now,
                "delta_seconds": delta_s,
                "diverges": diverge,
            },
            occurred_at=iso(host),
            occurred_at_source="host_clock",
        )
        self.conn.commit()
        return {
            "event_id": event_id,
            "host_now": iso(host),
            "claimed_now": claimed_now,
            "diverges": diverge,
            "delta_seconds": delta_s,
        }

    def _cap(self, claim_type: str, method: str, requested: float | None) -> float:
        cap = CONFIDENCE_CAPS.get((claim_type, method))
        if cap is None:
            cap = CONFIDENCE_CAPS.get((claim_type, "none"), 0.4)
        requested = 0.4 if requested is None else requested
        return min(requested, cap)

    def claim_propose(
        self,
        node_id: str,
        proposition: str,
        claim_type: str = "inference",
        confidence: float | None = None,
        confidence_basis: str = "model_proposal",
        falsification_condition: str | None = None,
        parent_claim_ids: list[str] | None = None,
        evidence_event_ids: list[str] | None = None,
        verification_method: str = "none",
        scope: str | None = None,
    ) -> dict[str, Any]:
        node = self._node(node_id)
        if verification_method in VERIFY_METHODS:
            raise LedgerError("use claim_verify to attach non-introspective verification")
        conf = self._cap(claim_type, verification_method, confidence)
        claim_id = str(uuid.uuid4())
        event_id = self._event(
            node_id,
            "system",
            {"op": "propose", "proposition": proposition},
        )
        self.conn.execute(
            """INSERT INTO claims
               (claim_id, lineage_id, branch_id, proposition, scope, originating_node,
                originating_event, parent_claim_ids, claim_type, status,
                verification_method, falsification_condition, confidence_basis,
                confidence, learned_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'proposed', ?, ?, ?, ?, ?)""",
            (
                claim_id,
                node.lineage_id,
                node.branch_id,
                proposition,
                scope,
                node_id,
                event_id,
                json.dumps(parent_claim_ids or []),
                claim_type,
                verification_method,
                falsification_condition,
                confidence_basis,
                conf,
                iso(now_utc()),
            ),
        )
        for eid in evidence_event_ids or []:
            self.conn.execute(
                "INSERT INTO evidence_refs (claim_id, event_id) VALUES (?, ?)",
                (claim_id, eid),
            )
        row = self._claim(claim_id)
        self._mutate(claim_id, event_id, node_id, "propose", row, "proposed", conf)
        self.conn.commit()
        return self.claim_view(claim_id)

    def claim_verify(
        self,
        node_id: str,
        claim_id: str,
        method: str,
        evidence_payload: dict[str, Any],
        new_confidence: float | None = None,
        occurred_at: str | None = None,
    ) -> dict[str, Any]:
        if method not in VERIFY_METHODS:
            raise LedgerError("verification method cannot raise confidence")
        before = self._claim(claim_id)
        event_id = self._event(
            node_id,
            "external_check",
            {"op": "verify", "claim_id": claim_id, "method": method, **evidence_payload},
            occurred_at=occurred_at,
            occurred_at_source=method,
        )
        after_conf = before["confidence"] if new_confidence is None else new_confidence
        after_conf = min(max(after_conf, before["confidence"]), 0.95)
        new_status = "current" if before["status"] in {"proposed", "current", "stale"} else before["status"]
        if before["status"] == "disputed":
            new_status = "disputed"
        self.conn.execute(
            """UPDATE claims SET verification_method=?, last_verified_at=?,
               confidence=?, status=? WHERE claim_id=?""",
            (method, iso(now_utc()), after_conf, new_status, claim_id),
        )
        self.conn.execute(
            "INSERT INTO evidence_refs (claim_id, event_id) VALUES (?, ?)",
            (claim_id, event_id),
        )
        self._mutate(claim_id, event_id, node_id, "verify", before, new_status, after_conf)
        self.conn.commit()
        return self.claim_view(claim_id)

    def claim_dispute(self, node_id: str, claim_id_a: str, claim_id_b: str, note: str | None = None) -> dict[str, Any]:
        if claim_id_a == claim_id_b:
            raise LedgerError("cannot dispute a claim with itself")
        a = self._claim(claim_id_a)
        b = self._claim(claim_id_b)
        event_id = self._event(
            node_id,
            "system",
            {"op": "dispute", "a": claim_id_a, "b": claim_id_b, "note": note},
        )
        for row, cid in ((a, claim_id_a), (b, claim_id_b)):
            self.conn.execute(
                "UPDATE claims SET status='disputed' WHERE claim_id=?",
                (cid,),
            )
            self._mutate(cid, event_id, node_id, "dispute", row, "disputed", row["confidence"])
        cid = str(uuid.uuid4())
        self.conn.execute(
            """INSERT INTO contradictions
               (contradiction_id, claim_a, claim_b, status, note, created_at)
               VALUES (?, ?, ?, 'open', ?, ?)""",
            (cid, claim_id_a, claim_id_b, note, iso(now_utc())),
        )
        self.conn.commit()
        return {"contradiction_id": cid, "claim_a": claim_id_a, "claim_b": claim_id_b, "status": "open"}

    def propose_reinforcement(
        self,
        node_id: str,
        claim_id: str,
        reason: str = "repeated_recall",
    ) -> dict[str, Any]:
        """Dreaming / persona recall may note repetition. It may not raise confidence."""
        before = self._claim(claim_id)
        event_id = self._event(
            node_id,
            "compression",
            {"op": "propose_reinforcement", "claim_id": claim_id, "reason": reason},
        )
        self._mutate(
            claim_id,
            event_id,
            node_id,
            "reinforce",
            before,
            before["status"],
            before["confidence"],
        )
        self.conn.commit()
        view = self.claim_view(claim_id)
        view["reinforcement_recorded"] = True
        view["confidence_delta_allowed"] = False
        return view

    def claim_supersede(
        self,
        node_id: str,
        old_claim_id: str,
        proposition: str,
        reason: str,
        claim_type: str | None = None,
    ) -> dict[str, Any]:
        old = self._claim(old_claim_id)
        event_id = self._event(
            node_id,
            "system",
            {"op": "supersede", "old": old_claim_id, "reason": reason},
        )
        self.conn.execute(
            "UPDATE claims SET status='superseded' WHERE claim_id=?",
            (old_claim_id,),
        )
        self._mutate(
            old_claim_id,
            event_id,
            node_id,
            "supersede",
            old,
            "superseded",
            old["confidence"],
        )
        new = self.claim_propose(
            node_id=node_id,
            proposition=proposition,
            claim_type=claim_type or old["claim_type"],
            confidence=min(old["confidence"], 0.4),
            confidence_basis=f"supersedes:{old_claim_id}|{reason}",
            parent_claim_ids=[old_claim_id],
            falsification_condition=old["falsification_condition"],
        )
        return {"old": self.claim_view(old_claim_id), "new": new}

    def lineage_branch(self, from_node_id: str, new_branch_id: str) -> Node:
        parent = self._node(from_node_id)
        child = self.session_open(
            parent.lineage_id,
            branch_id=new_branch_id,
            parent_node_ids=[from_node_id],
        )
        self._event(child.node_id, "branch", {"from": from_node_id, "to": new_branch_id})
        self.conn.commit()
        return child

    def lineage_merge(
        self,
        into_node_id: str,
        from_branch_ids: list[str],
        strategy: str = "keep_disputes",
    ) -> dict[str, Any]:
        into = self._node(into_node_id)
        open_rows = self.conn.execute(
            """SELECT * FROM contradictions WHERE status='open'
               AND claim_a IN (SELECT claim_id FROM claims WHERE lineage_id=?)
               AND claim_b IN (SELECT claim_id FROM claims WHERE lineage_id=?)""",
            (into.lineage_id, into.lineage_id),
        ).fetchall()
        if strategy == "require_resolution" and open_rows:
            raise LedgerError("open contradictions block merge")
        event_id = self._event(
            into_node_id,
            "merge",
            {"from_branch_ids": from_branch_ids, "strategy": strategy, "open": len(open_rows)},
        )
        self.conn.commit()
        return {
            "event_id": event_id,
            "open_contradictions": len(open_rows),
            "strategy": strategy,
            "branches": from_branch_ids,
        }

    def claim_explain(self, claim_id: str) -> dict[str, Any]:
        c = self.claim_view(claim_id)
        muts = [
            dict(r)
            for r in self.conn.execute(
                "SELECT * FROM claim_mutations WHERE claim_id=? ORDER BY recorded_at",
                (claim_id,),
            ).fetchall()
        ]
        cons = [
            dict(r)
            for r in self.conn.execute(
                "SELECT * FROM contradictions WHERE claim_a=? OR claim_b=?",
                (claim_id, claim_id),
            ).fetchall()
        ]
        ev = [
            r["event_id"]
            for r in self.conn.execute(
                "SELECT event_id FROM evidence_refs WHERE claim_id=?",
                (claim_id,),
            ).fetchall()
        ]
        return {"claim": c, "mutations": muts, "contradictions": cons, "evidence_event_ids": ev}

    def memory_context(
        self,
        query: str,
        lineage_id: str,
        token_budget: int = 2000,
        include_disputed: bool = True,
    ) -> dict[str, Any]:
        rows = self.conn.execute(
            "SELECT * FROM claims WHERE lineage_id=?",
            (lineage_id,),
        ).fetchall()
        q = query.lower()
        scored: list[ScoredClaim] = []
        for r in rows:
            lex = 1.0 if q and q in r["proposition"].lower() else (0.4 if r["status"] in {"current", "disputed"} else 0.1)
            ev_count = self.conn.execute(
                "SELECT COUNT(*) AS n FROM evidence_refs WHERE claim_id=?",
                (r["claim_id"],),
            ).fetchone()["n"]
            con_count = self.conn.execute(
                "SELECT COUNT(*) AS n FROM contradictions WHERE status='open' AND (claim_a=? OR claim_b=?)",
                (r["claim_id"], r["claim_id"]),
            ).fetchone()["n"]
            scored.append(
                ScoredClaim(
                    claim_id=r["claim_id"],
                    proposition=r["proposition"],
                    claim_type=r["claim_type"],
                    status=r["status"],
                    confidence=r["confidence"],
                    confidence_basis=r["confidence_basis"],
                    verification_method=r["verification_method"],
                    last_verified_at=parse_ts(r["last_verified_at"]),
                    falsification_condition=r["falsification_condition"],
                    evidence_count=ev_count,
                    contradiction_count=con_count,
                    learned_at=parse_ts(r["learned_at"]) or now_utc(),
                    lexical_score=lex,
                    semantic_score=lex,
                )
            )
        packet = build_packet(scored, token_budget=token_budget)
        # Rule 5: retrieving a consequential claim must attach open disputes.
        disputes = [
            dict(r)
            for r in self.conn.execute(
                """SELECT * FROM contradictions WHERE status='open'
                   AND (claim_a IN (SELECT claim_id FROM claims WHERE lineage_id=?)
                        OR claim_b IN (SELECT claim_id FROM claims WHERE lineage_id=?))""",
                (lineage_id, lineage_id),
            ).fetchall()
        ]
        packed_ids = {c.claim_id for c in packet.claims}
        for d in disputes:
            if d["claim_a"] in packed_ids or d["claim_b"] in packed_ids or include_disputed:
                for cid in (d["claim_a"], d["claim_b"]):
                    if cid not in packed_ids:
                        extra = next((c for c in scored if c.claim_id == cid), None)
                        if extra:
                            packet.claims.append(extra)
                            packed_ids.add(cid)
                            packet.warnings.append(
                                f"attached disputed counterpart {cid} (retrieval must not hide dissent)"
                            )
        successor = self._successor_summary(lineage_id)
        return {
            "persona": packet.persona,
            "claims": [c.__dict__ | {"last_verified_at": iso(c.last_verified_at), "learned_at": iso(c.learned_at)} for c in packet.claims],
            "disputes": disputes,
            "warnings": packet.warnings,
            "successor_summary": successor,
        }

    def _successor_summary(self, lineage_id: str) -> str:
        open_d = self.conn.execute(
            """SELECT c.claim_a, c.claim_b, a.proposition AS pa, b.proposition AS pb,
                      a.branch_id AS ba, b.branch_id AS bb
               FROM contradictions c
               JOIN claims a ON a.claim_id = c.claim_a
               JOIN claims b ON b.claim_id = c.claim_b
               WHERE c.status='open' AND a.lineage_id=?""",
            (lineage_id,),
        ).fetchall()
        if not open_d:
            return "No open contradictions in this lineage."
        parts = []
        for r in open_d:
            parts.append(
                f"UNRESOLVED: branch {r['ba']} asserted {r['pa']!r}; "
                f"branch {r['bb']} asserted {r['pb']!r}. "
                "Neither side has a resolving verification."
            )
        return " ".join(parts)

    def claim_view(self, claim_id: str) -> dict[str, Any]:
        return dict(self._claim(claim_id))

    def _claim(self, claim_id: str) -> sqlite3.Row:
        row = self.conn.execute("SELECT * FROM claims WHERE claim_id=?", (claim_id,)).fetchone()
        if row is None:
            raise LedgerError(f"unknown claim {claim_id}")
        return row

    def _node(self, node_id: str) -> Node:
        row = self.conn.execute("SELECT * FROM nodes WHERE node_id=?", (node_id,)).fetchone()
        if row is None:
            raise LedgerError(f"unknown node {node_id}")
        return Node(
            node_id=row["node_id"],
            lineage_id=row["lineage_id"],
            branch_id=row["branch_id"],
            parent_node_ids=json.loads(row["parent_node_ids"]),
            agent_label=row["agent_label"],
            model_label=row["model_label"],
        )
