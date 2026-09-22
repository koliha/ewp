"""Release metadata. Hashes change only with an explicit version bump."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

FROZEN_FILES = [
    "protocol/fixtures.py",
    "protocol/pathological.py",
    "protocol/pathological_fixtures.py",
    "protocol/classify.py",
    "protocol/warrant.py",
    "protocol/warrant_b.py",
    "protocol/types.py",
    "protocol/versions.py",
]


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_path(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def fixture_set_hash() -> str:
    h = hashlib.sha256()
    for rel in ("protocol/fixtures.py", "protocol/pathological.py"):
        h.update(Path(ROOT / rel).read_bytes())
    return h.hexdigest()


def evaluator_set_hash() -> str:
    h = hashlib.sha256()
    for rel in (
        "protocol/classify.py",
        "protocol/warrant.py",
        "protocol/warrant_b.py",
        "protocol/types.py",
        "protocol/may_act.py",
    ):
        h.update(Path(ROOT / rel).read_bytes())
    return h.hexdigest()


def golden_set_hash() -> str:
    h = hashlib.sha256()
    gold = ROOT / "tests" / "golden_warrantviews"
    for path in sorted(gold.glob("*.json")):
        h.update(path.name.encode())
        h.update(path.read_bytes())
    return h.hexdigest()


def metadata() -> dict:
    return {
        "protocol": "EWP-0.2.0",
        "short_name": "EWP",
        "policy": "reference-v1",
        "fixtures": "canonical-14 + pathological-12",
        "fixture_set_sha256": fixture_set_hash(),
        "evaluator_set_sha256": evaluator_set_hash(),
        "golden_set_sha256": golden_set_hash(),
        "graphiti_pin": "0.30.2",
        "rule": "Graphiti adapts to the protocol. The protocol does not adapt to Graphiti.",
    }


def write_lock() -> Path:
    path = ROOT / "RELEASE.lock.json"
    path.write_text(json.dumps(metadata(), indent=2) + "\n")
    return path
