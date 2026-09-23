"""Freeze reference WarrantViews. Do not regenerate to match a store."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from protocol.fixtures import EVAL, EVAL_LATE
from protocol.pathological import PACK
from protocol.types import Policy
from protocol.warrant import warrant_now
from tests.runner import FIXTURES

ROOT = Path(__file__).resolve().parents[1] / "tests" / "golden_warrantviews"
POLICY = Policy()


def dump(name: str, view, evaluated_at: str) -> None:
    w = warrant_now(view, POLICY, evaluated_at).normalized()
    path = ROOT / f"{name}.json"
    path.write_text(json.dumps(w, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(path.name)


def main() -> None:
    ROOT.mkdir(parents=True, exist_ok=True)
    for name, cases in FIXTURES:
        _pid, view, evaluated_at = cases[0]
        dump(name, view, evaluated_at)
    for name, factory in PACK:
        dump(name, factory(), EVAL)


if __name__ == "__main__":
    main()
