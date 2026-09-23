#!/usr/bin/env python3
"""Third evaluator. Reads only this directory.

Does not import protocol.warrant, protocol.classify, or protocol.warrant_b.
Policy tables come from policy.json. Rules come from POLICY.md.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
POLICY = json.loads((HERE / "policy.json").read_text(encoding="utf-8"))
RANK = {"NONE": 0, "INDIRECT": 1, "EXTERNAL": 2, "HUMAN": 3}
AXES = ("acceptance", "conflict", "verification", "currency", "sufficiency")


class InvalidView(ValueError):
    pass


def instant(ts: str) -> datetime:
    text = (ts or "").strip().replace("Z", "+00:00")
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def origin_of(check: dict) -> str:
    return (check.get("source") or {}).get("origin_type") or ""


def validate(view: dict) -> None:
    """POLICY.md: a value outside a closed enum makes the view invalid."""
    enums = POLICY["enums"]
    for e in view.get("evidence") or []:
        if e.get("polarity") not in enums["polarity"]:
            raise InvalidView(f"polarity {e.get('polarity')!r}")
    for c in view.get("checks") or []:
        if c.get("result") not in enums["result"]:
            raise InvalidView(f"result {c.get('result')!r}")
    for c in view.get("conflicts") or []:
        if c.get("status") not in enums["conflict_status"]:
            raise InvalidView(f"status {c.get('status')!r}")
    for e in view.get("lineage") or []:
        if e.get("kind") not in enums["lineage_kind"]:
            raise InvalidView(f"kind {e.get('kind')!r}")


def scope_caps_check(check: dict, view: dict) -> bool:
    """Declared ids compared exactly. Caps unless both are empty or they share one."""
    check_ids = {str(s).lower() for s in (check.get("subjects") or [])}
    view_ids = {str(s).lower() for s in (view.get("subjects") or [])}
    if not check_ids and not view_ids:
        return False
    return not (check_ids & view_ids)


def available_at(observed_at: str, evaluated_at: str | None) -> bool:
    """Missing or unparsable instants are not available at T."""
    if not observed_at:
        return False
    if not evaluated_at:
        return True
    try:
        return instant(observed_at) <= instant(evaluated_at)
    except ValueError:
        return False


def names_proposition(node: str, pid: str) -> bool:
    return node == pid or node.startswith(pid + ":")


def class_of(check: dict, view: dict, evaluated_at: str | None = None) -> str:
    if not available_at(check.get("observed_at") or "", evaluated_at):
        return "NONE"
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


def verification_of(view: dict, evaluated_at: str | None = None) -> str:
    best = "NONE"
    for check in view.get("checks") or []:
        cls = class_of(check, view, evaluated_at)
        if RANK[cls] > RANK[best]:
            best = cls
    return best


def conflict_of(view: dict, evaluated_at: str | None = None) -> str:
    rows = view.get("conflicts") or []
    if any(c.get("status") == "open" for c in rows):
        return "OPEN"
    polarities = {
        e.get("polarity")
        for e in view.get("evidence") or []
        if available_at(e.get("observed_at") or "", evaluated_at)
    }
    results = {
        c.get("result")
        for c in view.get("checks") or []
        if available_at(c.get("observed_at") or "", evaluated_at)
    }
    if ("supports" in polarities or "supports" in results) and (
        "opposes" in polarities or "opposes" in results
    ):
        return "OPEN"
    if any(c.get("status") == "resolved" for c in rows):
        return "RESOLVED"
    return "NONE"


def sufficiency_of(view: dict, evaluated_at: str | None = None) -> str:
    if (
        view.get("degraded")
        or view.get("omitted_sources")
        or (view.get("retrieval_scope") or "complete") != "complete"
    ):
        return "DEGRADED"
    assertions = [a for a in view.get("assertions") or [] if available_at(a.get("asserted_at") or "", evaluated_at)]
    evidence = [e for e in view.get("evidence") or [] if available_at(e.get("observed_at") or "", evaluated_at)]
    checks = [c for c in view.get("checks") or [] if available_at(c.get("observed_at") or "", evaluated_at)]
    if not assertions and not evidence and not checks:
        return "INSUFFICIENT"
    return "SUFFICIENT"


def currency_of(view: dict, verification: str, evaluated_at: str) -> tuple[str, bool]:
    pid = view["proposition_id"]
    if any(
        e.get("kind") == "superseded_by" and names_proposition(str(e.get("from_id") or ""), pid)
        for e in view.get("lineage") or []
    ):
        return "SUPERSEDED", False
    conferring = [
        c
        for c in view.get("checks") or []
        if verification != "NONE" and class_of(c, view, evaluated_at) == verification
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


def acceptance_of(view: dict, verification: str, conflict: str, currency: str, sufficiency: str, stale: bool, evaluated_at: str | None = None) -> str:
    supporting = [e for e in view.get("evidence") or [] if e.get("polarity") == "supports" and available_at(e.get("observed_at") or "", evaluated_at)]
    assertions = [a for a in view.get("assertions") or [] if available_at(a.get("asserted_at") or "", evaluated_at)]
    if not assertions and not supporting:
        return "UNACCEPTED"
    opposing_high = any(
        c.get("result") == "opposes" and class_of(c, view, evaluated_at) in {"EXTERNAL", "HUMAN"}
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
    validate(view)
    evaluated_at = view["evaluated_at"]
    verification = verification_of(view, evaluated_at)
    conflict = conflict_of(view, evaluated_at)
    sufficiency = sufficiency_of(view, evaluated_at)
    currency, stale = currency_of(view, verification, evaluated_at)
    acceptance = acceptance_of(view, verification, conflict, currency, sufficiency, stale, evaluated_at)
    return {
        "acceptance": acceptance,
        "conflict": conflict,
        "verification": verification,
        "currency": currency,
        "sufficiency": sufficiency,
        "protocol_version": POLICY["protocol"],
        "policy_version": POLICY["version"],
        "evaluated_at": evaluated_at,
    }


def classify_disagreement(name: str, got: dict, expected: dict) -> str:
    diffs = [ax for ax in AXES if got.get(ax) != expected.get(ax)]
    note = ",".join(diffs)
    if ("scope" in name or "subject" in name) and "verification" in diffs:
        return f"spec? subject binding in policy.json vs POLICY.md ({note})"
    if "episode" in name and "verification" in diffs:
        return f"spec? trusted-origin allowlist ({note})"
    return f"impl ({note})"


def main() -> int:
    fixtures = HERE / "fixtures"
    expected_dir = HERE / "expected"
    rows = []
    failed = 0
    for path in sorted(fixtures.glob("*.json")):
        view = json.loads(path.read_text(encoding="utf-8"))
        exp_path = expected_dir / path.name
        if not exp_path.exists():
            rows.append((path.stem, "—", "MISSING", "pack"))
            failed += 1
            continue
        expected = json.loads(exp_path.read_text(encoding="utf-8"))
        if expected.get("protocol_version") != POLICY["protocol"] or expected.get("policy_version") != POLICY["version"]:
            rows.append((path.stem, "—", "IDENTITY", "expected file names a different protocol/policy"))
            failed += 1
            continue
        got = warrant_now(view)
        match = all(got[ax] == expected[ax] for ax in AXES)
        klass = "—" if match else classify_disagreement(path.stem, got, expected)
        if not match:
            failed += 1
        rows.append((path.stem, got["verification"] + "/" + got["acceptance"], expected["verification"] + "/" + expected["acceptance"], klass))

    print("fixture                                   got            expected       class")
    print("-" * 88)
    for name, got, exp, klass in rows:
        print(f"{name:41} {got:14} {exp:14} {klass}")
    print()
    print(f"{len(rows) - failed}/{len(rows)} axis matches")
    if failed:
        print("Result: DISAGREEMENT")
        return 1
    print("Result: THIRD EVALUATOR MATCHES IMPLEMENTER EXPECTED AXES")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
