#!/usr/bin/env python3
"""Third evaluator. Reads only this directory.

Does not import protocol.warrant, protocol.classify, or protocol.warrant_b.
Policy tables come from policy.json. Rules come from POLICY.md.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
POLICY = json.loads((HERE / "policy.json").read_text())
RANK = {"NONE": 0, "INDIRECT": 1, "EXTERNAL": 2, "HUMAN": 3}
FAMILIES = ("server", "host", "node", "device", "serial")
ENTITY_RE = re.compile(r"(?:server|host|node|device|serial)[\w.-]*", re.I)
AXES = ("acceptance", "conflict", "verification", "currency", "sufficiency")


def instant(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def origin_of(check: dict) -> str:
    return (check.get("source") or {}).get("origin_type") or ""


def entities(text: str) -> set[str]:
    return {m.group(0).lower() for m in ENTITY_RE.finditer(text or "")}


def family(tok: str) -> str:
    for fam in FAMILIES:
        if tok.startswith(fam):
            return fam
    return tok


def scope_caps_check(check: dict, view: dict) -> bool:
    scope = (check.get("scope") or "").strip()
    if not scope:
        return False
    hay = " ".join(
        [view.get("proposition_id") or ""]
        + [a.get("text") or "" for a in view.get("assertions") or []]
        + [e.get("content") or "" for e in view.get("evidence") or []]
    )
    view_ents = entities(hay)
    for token in entities(scope):
        fam = family(token)
        same = {v for v in view_ents if family(v) == fam}
        if same and token not in same:
            return True
    return False


def class_of(check: dict, view: dict) -> str:
    method = check.get("method") or ""
    origin = origin_of(check)
    trusted = origin in POLICY["trusted_origins"]
    endogenous = origin in POLICY["endogenous_origins"]
    result = check.get("result")

    if method in POLICY["human_methods"]:
        cls = "HUMAN" if trusted and not endogenous else "INDIRECT"
    elif method in POLICY["external_methods"]:
        cls = "EXTERNAL" if trusted and not endogenous else "INDIRECT"
    elif method in POLICY["indirect_methods"]:
        cls = "INDIRECT"
    else:
        cls = "NONE"

    if scope_caps_check(check, view) and RANK[cls] >= RANK["EXTERNAL"]:
        cls = "INDIRECT"
    if result == "inconclusive" and RANK[cls] >= RANK["EXTERNAL"]:
        cls = "INDIRECT"
    return cls


def verification_of(view: dict) -> str:
    best = "NONE"
    for check in view.get("checks") or []:
        cls = class_of(check, view)
        if RANK[cls] > RANK[best]:
            best = cls
    return best


def conflict_of(view: dict) -> str:
    rows = view.get("conflicts") or []
    if any(c.get("status") == "open" for c in rows):
        return "OPEN"
    polarities = {e.get("polarity") for e in view.get("evidence") or []}
    results = {c.get("result") for c in view.get("checks") or []}
    if ("supports" in polarities or "supports" in results) and (
        "opposes" in polarities or "opposes" in results
    ):
        return "OPEN"
    if any(c.get("status") == "resolved" for c in rows):
        return "RESOLVED"
    return "NONE"


def sufficiency_of(view: dict) -> str:
    if (
        view.get("degraded")
        or view.get("omitted_sources")
        or (view.get("retrieval_scope") or "complete") != "complete"
    ):
        return "DEGRADED"
    if not view.get("assertions") and not view.get("evidence") and not view.get("checks"):
        return "INSUFFICIENT"
    return "SUFFICIENT"


def currency_of(view: dict, verification: str, evaluated_at: str) -> tuple[str, bool]:
    if any(e.get("kind") == "superseded_by" for e in view.get("lineage") or []):
        return "SUPERSEDED", False
    conferring = [
        c
        for c in view.get("checks") or []
        if verification != "NONE" and class_of(c, view) == verification
    ]
    stale = False
    if conferring:
        newest = max(conferring, key=lambda c: instant(c["observed_at"]))
        age = (instant(evaluated_at) - instant(newest["observed_at"])).total_seconds()
        limit = view.get("freshness_policy_seconds")
        if limit is None:
            limit = 86400 * 30
        stale = age > limit
    if stale:
        return "STALE", True
    return "CURRENT", stale


def acceptance_of(view: dict, verification: str, conflict: str, currency: str, sufficiency: str, stale: bool) -> str:
    supporting = [e for e in view.get("evidence") or [] if e.get("polarity") == "supports"]
    if not view.get("assertions") and not supporting:
        return "UNACCEPTED"
    opposing_high = any(
        c.get("result") == "opposes" and class_of(c, view) in {"EXTERNAL", "HUMAN"}
        for c in view.get("checks") or []
    )
    if (
        verification in {"EXTERNAL", "HUMAN"}
        and conflict != "OPEN"
        and currency != "SUPERSEDED"
        and sufficiency == "SUFFICIENT"
        and not stale
        and not opposing_high
    ):
        return "ACCEPTED"
    return "TENTATIVE"


def warrant_now(view: dict) -> dict:
    evaluated_at = view["evaluated_at"]
    verification = verification_of(view)
    conflict = conflict_of(view)
    sufficiency = sufficiency_of(view)
    currency, stale = currency_of(view, verification, evaluated_at)
    acceptance = acceptance_of(view, verification, conflict, currency, sufficiency, stale)
    return {
        "acceptance": acceptance,
        "conflict": conflict,
        "verification": verification,
        "currency": currency,
        "sufficiency": sufficiency,
        "policy_version": POLICY["version"],
        "evaluated_at": evaluated_at,
    }


def classify_disagreement(name: str, got: dict, expected: dict) -> str:
    diffs = [ax for ax in AXES if got.get(ax) != expected.get(ax)]
    note = ",".join(diffs)
    if "scope" in name and "verification" in diffs:
        return f"spec? scope notes in policy.json vs POLICY.md ({note})"
    if "episode" in name and "verification" in diffs:
        return f"spec? trusted-origin allowlist ({note})"
    return f"impl ({note})"


def main() -> int:
    fixtures = HERE / "fixtures"
    expected_dir = HERE / "expected"
    rows = []
    failed = 0
    for path in sorted(fixtures.glob("*.json")):
        view = json.loads(path.read_text())
        exp_path = expected_dir / path.name
        if not exp_path.exists():
            rows.append((path.stem, "—", "MISSING", "pack"))
            failed += 1
            continue
        expected = json.loads(exp_path.read_text())
        got = warrant_now(view)
        match = all(got[ax] == expected[ax] for ax in AXES)
        klass = "—" if match else classify_disagreement(path.stem, got, expected)
        if not match:
            failed += 1
        rows.append((path.stem, got["verification"] + "/" + got["acceptance"], expected["verification"] + "/" + expected["acceptance"], klass))

    print("fixture                                 got            expected       class")
    print("-" * 86)
    for name, got, exp, klass in rows:
        print(f"{name:39} {got:14} {exp:14} {klass}")
    print()
    print(f"{len(rows) - failed}/{len(rows)} axis matches")
    if failed:
        print("Result: DISAGREEMENT")
        return 1
    print("Result: THIRD EVALUATOR MATCHES IMPLEMENTER EXPECTED AXES")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
