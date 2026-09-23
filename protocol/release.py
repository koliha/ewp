"""Release metadata. Hashes change only with an explicit version bump.

Every hash is over file content with CRLF normalized to LF, so a Windows
checkout and a Linux checkout of the same commit produce the same lock.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .versions import GRAPHITI_PIN, POLICY, PROTOCOL

ROOT = Path(__file__).resolve().parents[1]

# Behavioral fixtures: canonical, pathological, and the hardening pack.
FIXTURE_FILES = (
    "protocol/fixtures.py",
    "protocol/pathological.py",
    "protocol/laundering.py",
)
# Everything that decides the axes or the action gate.
EVALUATOR_FILES = (
    "protocol/classify.py",
    "protocol/warrant.py",
    "protocol/warrant_b.py",
    "protocol/types.py",
    "protocol/may_act.py",
    "protocol/versions.py",
)
# The named policy as written for independent implementers.
POLICY_FILES = (
    "docs/implementer/POLICY.md",
    "docs/implementer/policy.json",
)
LOCK_KEYS = (
    "fixture_set_sha256",
    "evaluator_set_sha256",
    "policy_set_sha256",
    "golden_set_sha256",
    "implementer_pack_sha256",
)


def _normalized(path: Path) -> bytes:
    return path.read_bytes().replace(b"\r\n", b"\n")


def _hash_files(rels) -> str:
    h = hashlib.sha256()
    for rel in rels:
        h.update(rel.encode())
        h.update(_normalized(ROOT / rel))
    return h.hexdigest()


def _hash_dir(rel_dir: str) -> str:
    h = hashlib.sha256()
    base = ROOT / rel_dir
    for path in sorted(base.rglob("*.json")):
        h.update(path.relative_to(base).as_posix().encode())
        h.update(_normalized(path))
    return h.hexdigest()


def fixture_set_hash() -> str:
    return _hash_files(FIXTURE_FILES)


def evaluator_set_hash() -> str:
    return _hash_files(EVALUATOR_FILES)


def policy_set_hash() -> str:
    return _hash_files(POLICY_FILES)


def golden_set_hash() -> str:
    return _hash_dir("tests/golden_warrantviews")


def implementer_pack_hash() -> str:
    """docs/implementer fixtures + expected axes (all 50, including the hardening pack)."""
    h = hashlib.sha256()
    h.update(_hash_dir("docs/implementer/fixtures").encode())
    h.update(_hash_dir("docs/implementer/expected").encode())
    return h.hexdigest()


def current_hashes() -> dict[str, str]:
    return {
        "fixture_set_sha256": fixture_set_hash(),
        "evaluator_set_sha256": evaluator_set_hash(),
        "policy_set_sha256": policy_set_hash(),
        "golden_set_sha256": golden_set_hash(),
        "implementer_pack_sha256": implementer_pack_hash(),
    }


def metadata() -> dict:
    return {
        "protocol": PROTOCOL,
        "short_name": "EWP",
        "policy": POLICY,
        "fixtures": "canonical-14 + pathological-12 + hardening-24",
        **current_hashes(),
        "graphiti_pin": GRAPHITI_PIN,
        "rule": "Graphiti adapts to the protocol. The protocol does not adapt to Graphiti.",
    }


def write_lock() -> Path:
    path = ROOT / "RELEASE.lock.json"
    path.write_text(json.dumps(metadata(), indent=2) + "\n", encoding="utf-8", newline="\n")
    return path
