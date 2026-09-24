#!/usr/bin/env python3
"""Mem0Adapter against the real OSS client (mem0ai 2.x), when installed.

Runs offline: mem0's own MockEmbeddings and local Qdrant in a temp
directory, infer=False so no LLM is called. Skipped when mem0ai is not
installed; the GitHub workflow installs it.
"""

from __future__ import annotations

import dataclasses
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ.setdefault("MEM0_TELEMETRY", "false")
os.environ.setdefault("OPENAI_API_KEY", "unused-infer-is-false")

from ewp.codec import canonical_dict
from ewp.fixtures import EVAL, fixture_verified_current
from ewp.laundering import customer_scope_mismatch
from ewp.mem0_adapter import Mem0Adapter
from ewp.sqlite_adapter import LedgerError
from ewp.types import Policy
from ewp.warrant import warrant_now


def canonical(view):
    return canonical_dict(view)


def make_memory(tmp: str):
    from mem0 import Memory
    from mem0.embeddings.mock import MockEmbeddings

    memory = Memory.from_config({
        "vector_store": {"provider": "qdrant", "config": {
            "collection_name": "ewp", "path": str(Path(tmp) / "qdrant"), "embedding_model_dims": 10}},
        "history_db_path": str(Path(tmp) / "history.db"),
    })
    memory.embedding_model = MockEmbeddings()  # offline; 10 dimensions
    return memory


class DropsOne:
    """A read that silently loses one opposing evidence memory, as a lagging
    index or a partial page would."""

    def __init__(self, inner):
        self.inner = inner

    def __getattr__(self, name):
        return getattr(self.inner, name)

    def get_all(self, *, filters=None, top_k=20, show_expired=False, **kwargs):
        payload = self.inner.get_all(filters=filters, top_k=top_k, show_expired=show_expired, **kwargs)
        rows = payload["results"]
        for i, row in enumerate(rows):
            if (row.get("metadata") or {}).get("ewp", {}).get("polarity") == "opposes":
                del rows[i]
                break
        return payload


class DropsSidecar(DropsOne):
    """A read that loses the newest snapshot's sidecar but keeps its records."""

    def __init__(self, inner, view_id):
        super().__init__(inner)
        self.view_id = view_id

    def get_all(self, *, filters=None, top_k=20, show_expired=False, **kwargs):
        payload = self.inner.get_all(filters=filters, top_k=top_k, show_expired=show_expired, **kwargs)
        payload["results"] = [
            r for r in payload["results"]
            if not ((r.get("metadata") or {}).get("ewp", {}).get("kind") == "ewp_parked"
                    and r["metadata"]["ewp"].get("view_id") == self.view_id)
        ]
        return payload


def main() -> int:
    try:
        import importlib.metadata as md

        import mem0  # noqa: F401
    except ImportError:
        print("SKIP real Mem0 client test: pip install mem0ai")
        return 0
    version = md.version("mem0ai")
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:  # Qdrant keeps its file open on Windows
        memory = make_memory(tmp)
        adapter = Mem0Adapter(memory, user_id="u1", infer=False)

        # Round trip, including subjects and a mismatched check.
        for view in (fixture_verified_current(), customer_scope_mismatch()):
            adapter.ingest_view(view)
            back = adapter.raw_view(view.proposition_id)
            assert canonical(back) == canonical(view), view.proposition_id
            at = EVAL if view.proposition_id == "P-win" else "2026-09-22T12:00:00+00:00"
            assert warrant_now(back, Policy(), at).normalized()["warrant"] == warrant_now(view, Policy(), at).normalized()["warrant"]

        # Snapshots: v2 adds an opposing item; v1 stays exactly v1.
        base = fixture_verified_current()
        opposing = dataclasses.replace(base.evidence[0], evidence_id="e-opp", polarity="opposes",
                                       content="server01 runs Windows Server 2019")
        v2 = dataclasses.replace(base, view_id="v2", evidence=base.evidence + [opposing])
        adapter.ingest_view(v2)
        assert canonical(adapter.raw_view("P-win", base.view_id)) == canonical(base)
        assert canonical(adapter.raw_view("P-win")) == canonical(v2)
        assert warrant_now(adapter.raw_view("P-win"), Policy(), EVAL).warrant.conflict == "OPEN"

        # A read that loses the opposing memory must not pose as a complete snapshot.
        partial = Mem0Adapter(DropsOne(memory), user_id="u1", infer=False)
        try:
            partial.raw_view("P-win")
        except LedgerError:
            pass
        else:
            raise AssertionError("a partial Mem0 read was returned as the complete snapshot")

        # A read that loses the newest sidecar must not serve v1 as the latest.
        try:
            Mem0Adapter(DropsSidecar(memory, "v2"), user_id="u1", infer=False).raw_view("P-win")
        except LedgerError:
            pass
        else:
            raise AssertionError("an older snapshot was served as latest after losing the newest sidecar")

        # A read at the limit may be truncated: refused, not trusted.
        try:
            Mem0Adapter(memory, user_id="u1", infer=False, read_limit=3).raw_view("P-win")
        except LedgerError:
            pass
        else:
            raise AssertionError("a possibly truncated read was accepted")

        # Search goes through filters and stays inside the snapshot.
        found = adapter.search_view("P-win", "Windows", view_id="v2")
        assert found.retrieval_scope == "mem0.search"

        # Another user's memories never enter this user's view.
        Mem0Adapter(memory, user_id="u2", infer=False).ingest_view(
            dataclasses.replace(base, view_id="other-user", degraded=True))
        assert canonical(adapter.raw_view("P-win")) == canonical(v2)
    print(f"PASS Mem0Adapter against mem0ai {version} (OSS Memory): round trip, snapshots, "
          "partial read refused, lost newest sidecar refused, truncation refused, search, user scoping")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
