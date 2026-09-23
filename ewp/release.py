"""Release metadata. Hashes change only with an explicit version bump.

Every hash is over file content with CRLF normalized to LF, so a Windows
checkout and a Linux checkout of the same commit produce the same lock.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path

from .versions import FIXTURES, GRAPHITI_PIN, POLICY, PROTOCOL

ROOT = Path(__file__).resolve().parents[1]

# Behavioral fixtures: canonical, pathological, and the hardening pack.
FIXTURE_FILES = (
    "ewp/fixtures.py",
    "ewp/pathological.py",
    "ewp/laundering.py",
)
# Everything that decides the axes or the action gate.
EVALUATOR_FILES = (
    "ewp/classify.py",
    "ewp/warrant.py",
    "ewp/warrant_b.py",
    "ewp/types.py",
    "ewp/may_act.py",
    "ewp/versions.py",
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
    """docs/implementer fixtures + expected axes (canonical, pathological,
    hardening) + the invalid pack every evaluator must refuse."""
    h = hashlib.sha256()
    h.update(_hash_dir("docs/implementer/fixtures").encode())
    h.update(_hash_dir("docs/implementer/expected").encode())
    h.update(_hash_dir("docs/implementer/invalid").encode())
    return h.hexdigest()


CI_SURFACE_GLOBS = (
    "ewp/**/*.py",
    "tests/**/*.py",
    "docs/implementer/**/*",
    ".github/workflows/*.yml",
    "examples/*.json",
    "pyproject.toml",
)


def ci_surface_hash() -> str:
    """Everything tests/ci.py exercises: kernel, adapters, MCP, tests,
    implementer pack, workflow. Not part of the protocol lock; it ties a CI
    stamp to the exact CI surface it ran on."""
    files: set[Path] = set()
    for pattern in CI_SURFACE_GLOBS:
        files.update(p for p in ROOT.glob(pattern) if p.is_file() and "__pycache__" not in p.parts)
    h = hashlib.sha256()
    for path in sorted(files):
        h.update(path.relative_to(ROOT).as_posix().encode())
        h.update(_normalized(path))
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
        "fixtures": FIXTURES,
        **current_hashes(),
        "graphiti_pin": GRAPHITI_PIN,
        "rule": "Graphiti adapts to the protocol. The protocol does not adapt to Graphiti.",
    }


def write_text_atomic(path: Path, text: str, attempts: int = 10) -> None:
    """Write via a temp file and os.replace, retrying briefly: on Windows a
    scanner or indexer can hold a just-written file for a moment."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    for attempt in range(attempts):
        try:
            os.replace(tmp, path)
            return
        except OSError:
            if attempt == attempts - 1:
                raise
            time.sleep(0.2)


def write_lock() -> Path:
    path = ROOT / "RELEASE.lock.json"
    write_text_atomic(path, json.dumps(metadata(), indent=2) + "\n")
    return path
