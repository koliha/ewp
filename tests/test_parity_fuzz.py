#!/usr/bin/env python3
"""Differential fuzz: the reference kernel (codec + warrant_now + warrant_b)
against the independent third evaluator.

Every field of every implementer fixture, at every depth, is replaced by an
awkward value (null, "", 0, false, [], {}, a string, a huge integer, NaN, ...).
Both implementations must then refuse, or both must evaluate to the same five
axes, and neither may crash. Two evaluators that agree on the 52 fixtures but
split on malformed input would each be conformant and still disagree.
"""

from __future__ import annotations

import copy
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "docs" / "implementer"))

import third_eval  # noqa: E402
from ewp.classify import InvalidEvidenceView  # noqa: E402
from ewp.codec import view_from_dict  # noqa: E402
from ewp.types import Policy  # noqa: E402
from ewp.warrant import warrant_now  # noqa: E402
from ewp.warrant_b import axes_only  # noqa: E402

AXES = ("acceptance", "conflict", "verification", "currency", "sufficiency")
VALUES = [None, "", 0, -1, False, True, [], {}, "x", "supports", 1.5, 10**400, float("nan"), ["a"], [""], [1]]


def kernel(doc: dict) -> object:
    evaluated_at = doc.get("evaluated_at")
    view = {k: v for k, v in doc.items() if k != "evaluated_at"}
    try:
        v = view_from_dict(view)
        a = tuple(getattr(warrant_now(v, Policy(), evaluated_at).warrant, k) for k in AXES)
        b = axes_only(v, Policy(), evaluated_at)
        if a != tuple(b[k] for k in AXES):
            return ("A!=B", a, b)
        return a
    except (InvalidEvidenceView, ValueError):
        return "REFUSED"
    except Exception as exc:
        return f"CRASH {type(exc).__name__}: {exc}"[:160]


def third(doc: dict) -> object:
    try:
        r = third_eval.warrant_now(doc)
        return tuple(r[k] for k in AXES)
    except (third_eval.InvalidView, ValueError):
        return "REFUSED"
    except Exception as exc:
        return f"CRASH {type(exc).__name__}: {exc}"[:160]


def _paths(node, prefix=()):
    if isinstance(node, dict):
        for k, v in node.items():
            yield prefix + (k,)
            yield from _paths(v, prefix + (k,))
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield prefix + (i,)
            yield from _paths(v, prefix + (i,))


def main() -> int:
    fixtures = sorted((ROOT / "docs" / "implementer" / "fixtures").glob("*.json"))
    problems: Counter = Counter()
    example: dict = {}
    runs = 0
    for f in fixtures:
        base = json.loads(f.read_text(encoding="utf-8"))
        for path in list(_paths(base)):
            for value in VALUES:
                doc = copy.deepcopy(base)
                node = doc
                for p in path[:-1]:
                    node = node[p]
                node[path[-1]] = copy.deepcopy(value)
                k, t = kernel(doc), third(doc)
                runs += 1
                if k == t and not (isinstance(k, str) and k.startswith("CRASH")):
                    continue
                key = (str(path[-1]), "kernel " + str(k)[:40], "third " + str(t)[:40])
                problems[key] += 1
                example.setdefault(key, (f.name, path, repr(value)[:40]))
    if problems:
        for key, n in problems.most_common(20):
            print(f"FAIL {n:4}x field={key[0]} {key[1]} | {key[2]}  e.g. {example[key]}")
        return 1
    print(f"PASS kernel, second evaluator, and third evaluator agree on {runs} malformed views; none crash")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
