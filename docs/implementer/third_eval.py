#!/usr/bin/env python3
"""Third evaluator. Reads only this directory.

Does not import ewp.warrant, ewp.classify, or ewp.warrant_b.
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
    if ts is not None and not isinstance(ts, str):
        raise ValueError(f"timestamp {ts!r} is not a string")
    text = (ts or "").strip().replace("Z", "+00:00")
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def origin_of(check: dict) -> str:
    return (check.get("source") or {}).get("origin_type") or ""


def is_subject_list(value) -> bool:
    return value is None or (isinstance(value, list) and all(isinstance(s, str) and s for s in value))


def is_string_list(value, allow_empty: bool = True) -> bool:
    return isinstance(value, list) and (allow_empty or bool(value)) and all(isinstance(s, str) and s for s in value)


SOURCE_FIELDS = (
    "source_id", "lineage_id", "origin_type", "origin_locator", "snapshot_id",
    "content_hash", "observed_at", "extractor_id", "parent_source_id",
)
DEFAULTS = {"retrieval_scope": "complete", "degraded": False, "freshness_policy_seconds": 86400 * 30,
            "omitted_sources": [], "subjects": []}


def about(record: dict, pid: str) -> str:
    """A record's proposition; missing or null means the view's."""
    value = record.get("proposition_id")
    return pid if value is None else str(value)


def field(view: dict, key: str):
    """SCHEMA.md: a missing or null field takes its default; any present value is kept."""
    value = view.get(key)
    return DEFAULTS[key] if value is None else value


# SCHEMA.md required fields (optional ones: proposition_id on records, subjects,
# extractor_id, parent_source_id, note, and the view-level defaults).
REQUIRED = {
    "assertions": ("assertion_id", "text", "asserted_by", "assertion_confidence", "source", "asserted_at"),
    "evidence": ("evidence_id", "polarity", "source", "content", "observed_at"),
    "checks": ("check_id", "method", "scope", "source", "observed_at", "result"),
    "conflicts": ("conflict_id", "status"),
    "lineage": ("kind",),
}
REQUIRED_SOURCE = ("source_id", "lineage_id", "origin_type", "origin_locator", "snapshot_id", "content_hash", "observed_at")


def check_required(view: dict) -> None:
    if not isinstance(view.get("proposition_id"), str) or view["proposition_id"] == "":
        raise InvalidView("proposition_id must be a non-empty string")
    view_id = view.get("view_id")
    if view_id not in (None, "") and (isinstance(view_id, bool) or not isinstance(view_id, (str, int))):
        raise InvalidView(f"view_id {view_id!r} must be a string")
    for part, keys in REQUIRED.items():
        records = view.get(part)
        if records is None:
            continue
        if not isinstance(records, list):
            raise InvalidView(f"{part} must be a list")
        for r in records:
            if not isinstance(r, dict):
                raise InvalidView(f"{part} entry is not an object")
            for k in keys:
                if r.get(k) is None:
                    raise InvalidView(f"{part} record missing {k}")
            if "source" in keys:
                src = r["source"]
                if not isinstance(src, dict) or any(src.get(k) is None for k in REQUIRED_SOURCE):
                    raise InvalidView(f"{part} record has an incomplete source")
            if part == "assertions":
                confidence = r["assertion_confidence"]
                if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
                    raise InvalidView("assertion_confidence is not a JSON number")
                try:
                    confidence = float(confidence)
                except OverflowError:
                    raise InvalidView("assertion_confidence is too large to be a finite number") from None
                if confidence != confidence or confidence in (float("inf"), float("-inf")):
                    raise InvalidView("assertion_confidence must be finite")


def validate(view: dict) -> None:
    """POLICY.md "Input validation" and SCHEMA.md required fields: refuse, do not evaluate."""
    check_required(view)
    enums = POLICY["enums"]
    pid = view["proposition_id"]
    try:
        instant(view.get("evaluated_at") or "")
    except ValueError:
        raise InvalidView(f"evaluated_at {view.get('evaluated_at')!r}") from None
    for part, key in (("assertions", "assertion_id"), ("evidence", "evidence_id"), ("checks", "check_id"), ("conflicts", "conflict_id")):
        ids = [str(r.get(key)) for r in view.get(part) or []]
        if len(ids) != len(set(ids)):
            raise InvalidView(f"duplicate {key}")
    sources: dict = {}
    for part in ("assertions", "evidence", "checks"):
        for r in view.get(part) or []:
            s = r.get("source") or {}
            canonical = json.dumps({k: None if s.get(k) is None else str(s.get(k)) for k in SOURCE_FIELDS}, sort_keys=True)
            if sources.setdefault(str(s.get("source_id")), canonical) != canonical:
                raise InvalidView(f"source_id {s.get('source_id')!r} has two SourceRefs")
    if not is_string_list(field(view, "omitted_sources")):
        raise InvalidView("omitted_sources must be a list of strings")
    for a in view.get("assertions") or []:
        if not names_proposition(about(a, pid), pid):
            raise InvalidView(f"assertion about {a.get('proposition_id')!r}")
    for e in view.get("evidence") or []:
        if e.get("polarity") not in enums["polarity"]:
            raise InvalidView(f"polarity {e.get('polarity')!r}")
        if not names_proposition(about(e, pid), pid):
            raise InvalidView(f"evidence about {e.get('proposition_id')!r}")
    for c in view.get("checks") or []:
        if c.get("result") not in enums["result"]:
            raise InvalidView(f"result {c.get('result')!r}")
        if not is_subject_list(c.get("subjects")):
            raise InvalidView(f"check subjects {c.get('subjects')!r}")
    for c in view.get("conflicts") or []:
        if c.get("status") not in enums["conflict_status"]:
            raise InvalidView(f"status {c.get('status')!r}")
        if not is_string_list(c.get("proposition_ids"), allow_empty=False):
            raise InvalidView("conflict proposition_ids must be a non-empty list of strings")
        if not any(names_proposition(x, pid) for x in c["proposition_ids"]):
            raise InvalidView(f"conflict does not name {pid!r}")
    for e in view.get("lineage") or []:
        if e.get("kind") not in enums["lineage_kind"]:
            raise InvalidView(f"kind {e.get('kind')!r}")
        if not all(isinstance(e.get(k), str) and e.get(k) for k in ("from_id", "to_id")):
            raise InvalidView("lineage endpoints must be non-empty strings")
    if not is_subject_list(field(view, "subjects")):
        raise InvalidView(f"view subjects {view.get('subjects')!r}")
    fresh = field(view, "freshness_policy_seconds")
    if type(fresh) is not int or not 0 <= fresh <= 2**53 - 1:
        raise InvalidView(f"freshness_policy_seconds {fresh!r}")
    if type(field(view, "degraded")) is not bool:
        raise InvalidView(f"degraded {view.get('degraded')!r}")
    if not isinstance(field(view, "retrieval_scope"), str):
        raise InvalidView(f"retrieval_scope {view.get('retrieval_scope')!r}")
    if view.get("adapter_meta") is not None and not isinstance(view["adapter_meta"], dict):
        raise InvalidView("adapter_meta must be an object")


def scope_caps_check(check: dict, view: dict) -> bool:
    """Declared ids compared exactly. Caps unless both are empty or they share one."""
    check_ids = {str(s).lower() for s in (check.get("subjects") or [])}
    view_ids = {str(s).lower() for s in (view.get("subjects") or [])}
    if not check_ids and not view_ids:
        return False
    return not (check_ids & view_ids)


def available_at(observed_at: str, evaluated_at: str | None) -> bool:
    """Missing or unparsable instants are not available at T."""
    if observed_at is None or observed_at == "":
        return False
    if not evaluated_at:
        return True
    try:
        return instant(str(observed_at)) <= instant(evaluated_at)
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
    if field(view, "degraded") or field(view, "omitted_sources") or field(view, "retrieval_scope") != "complete":
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
        stale = age > field(view, "freshness_policy_seconds")
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
    fixture_files = sorted(fixtures.glob("*.json"))
    for path in fixture_files:
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

    axis_failed = failed
    # Invalid views: the only correct output is a refusal.
    refused = 0
    invalid_files = sorted((HERE / "invalid").glob("*.json"))
    for path in invalid_files:
        view = json.loads(path.read_text(encoding="utf-8"))
        try:
            got = warrant_now(view)
        except InvalidView:
            refused += 1
            rows.append((path.stem, "REFUSED", "REFUSED", "—"))
            continue
        failed += 1
        rows.append((path.stem, got["verification"] + "/" + got["acceptance"], "REFUSED", "impl (evaluated an invalid view)"))

    print("fixture                                   got            expected       class")
    print("-" * 88)
    for name, got, exp, klass in rows:
        print(f"{name:41} {got:14} {exp:14} {klass}")
    print()
    print(f"{len(fixture_files) - axis_failed}/{len(fixture_files)} axis matches")
    print(f"{refused}/{len(invalid_files)} invalid views refused")
    if failed:
        print("Result: DISAGREEMENT")
        return 1
    print("Result: THIRD EVALUATOR MATCHES IMPLEMENTER EXPECTED AXES AND REFUSES EVERY INVALID VIEW")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
