#!/usr/bin/env python3
"""Store-neutrality fuzz (a deterministic 1-in-8 sample, to keep CI fast).

Every field of every implementer fixture is replaced by awkward values. Each
malformed view the kernel ACCEPTS must round-trip through SQLite, the JSON
store, and Mem0 (the fake 2.x client) with the same canonical fields and the
same axes, and through fake Graphiti with the same axes (its field losses are
listed). A store that refuses, crashes on, or changes an accepted view is not
store-neutral, except Graphiti's one documented refusal: a source whose
records of one kind carry different times (one episode holds one time).
"""

from __future__ import annotations

import copy
import json
import shutil
import sys
import tempfile
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from ewp.classify import InvalidEvidenceView  # noqa: E402
from ewp.codec import canonical_dict, view_from_dict  # noqa: E402
from ewp.graphiti_adapter import GraphitiAdapter  # noqa: E402
from ewp.graphiti_ingest import ingest_view as ingest_graphiti  # noqa: E402
from ewp.graphiti_records import FakeGraphitiStore  # noqa: E402
from ewp.json_adapter import JsonFileAdapter  # noqa: E402
from ewp.mem0_adapter import Mem0Adapter  # noqa: E402
from ewp.sqlite_adapter import SQLiteAdapter  # noqa: E402
from ewp.types import Policy  # noqa: E402
from ewp.warrant import warrant_now  # noqa: E402
from test_live_adapters import FakeMem0  # noqa: E402

AXES = ("acceptance", "conflict", "verification", "currency", "sufficiency")
STRIDE = 8
VALUES = [None, "", 0, -1, False, True, [], {}, "x", "supports", 1.5, 10**400, float("nan"), ["a"], [""], [1]]


def _axes(view, evaluated_at):
    w = warrant_now(view, Policy(), evaluated_at).warrant
    return tuple(getattr(w, k) for k in AXES)


def _paths(node, prefix=()):
    if isinstance(node, dict):
        for k, v in node.items():
            yield prefix + (k,)
            yield from _paths(v, prefix + (k,))
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield prefix + (i,)
            yield from _paths(v, prefix + (i,))


def _round_trip(store_name: str, view, root: Path):
    if store_name == "sqlite":
        store = SQLiteAdapter()
        store.load_view(view)
        return store.get_view(view.proposition_id, view.view_id)
    if store_name == "json":
        store = JsonFileAdapter(root)
        store.load_view(view)
        return store.get_view(view.proposition_id, view.view_id)
    if store_name == "graphiti":
        store = FakeGraphitiStore()
        ingest_graphiti(store, view)
        return GraphitiAdapter(store).raw_view(view.proposition_id)
    store = Mem0Adapter(FakeMem0(), user_id="u", infer=False)
    store.ingest_view(view)
    return store.raw_view(view.proposition_id, view.view_id)


def main() -> int:
    fixtures = sorted((ROOT / "docs" / "implementer" / "fixtures").glob("*.json"))
    findings: Counter = Counter()
    example: dict = {}
    accepted = seen = 0
    tmp = Path(tempfile.mkdtemp())
    try:
        for f in fixtures:
            base = json.loads(f.read_text(encoding="utf-8"))
            for path in list(_paths(base)):
                for value in VALUES:
                    seen += 1
                    if seen % STRIDE:
                        continue
                    doc = copy.deepcopy(base)
                    node = doc
                    for p in path[:-1]:
                        node = node[p]
                    node[path[-1]] = copy.deepcopy(value)
                    evaluated_at = doc.pop("evaluated_at", None)
                    try:
                        view = view_from_dict(doc)
                        want = _axes(view, evaluated_at)
                    except (InvalidEvidenceView, ValueError):
                        continue
                    accepted += 1
                    want_fields = canonical_dict(view)
                    for store_name in ("sqlite", "json", "mem0", "graphiti"):
                        try:
                            got = _round_trip(store_name, view, tmp / str(seen))
                            problem = None
                            if store_name != "graphiti" and canonical_dict(got) != want_fields:
                                problem = "fields changed"
                            elif _axes(got, evaluated_at) != want:
                                problem = "axes changed"
                        except ValueError as exc:
                            if store_name == "graphiti" and "one time per episode" in str(exc):
                                continue
                            problem = f"ValueError: {str(exc)[:70]}"
                        except Exception as exc:
                            problem = f"{type(exc).__name__}: {str(exc)[:70]}"
                        if problem:
                            key = (store_name, str(path[-1]), problem[:60])
                            findings[key] += 1
                            example.setdefault(key, (f.name, path, repr(value)[:30]))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    if findings:
        for key, n in findings.most_common(20):
            print(f"FAIL {n:5} {key}  e.g. {example[key]}")
        return 1
    print(f"PASS {accepted} accepted malformed views are store-neutral through SQLite, JSON, Mem0, and fake Graphiti")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
