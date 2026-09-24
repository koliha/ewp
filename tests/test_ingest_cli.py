#!/usr/bin/env python3
"""ewp-ingest: the operator's path from a JSON file to a ledger the agent can read."""

from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ewp.ingest_cli import main as ingest
from ewp.sqlite_adapter import SQLiteAdapter

EXAMPLE = str(ROOT / "examples" / "quickstart.json")
T = "2026-09-23T12:00:00Z"


def run(*argv: str) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = ingest(list(argv))
    return code, out.getvalue(), err.getvalue()


def test_quickstart_example():
    with tempfile.TemporaryDirectory() as tmp:
        db = str(Path(tmp) / "ledger.sqlite")
        code, out, err = run("--db", db, EXAMPLE, "--evaluated-at", T)
        assert code == 1 and "--attest-trusted-origins" in err, (code, err)
        assert "P-api-key-rotated" in out and "P-prod-db-version" not in out, out
        code, out, err = run("--db", db, EXAMPLE, "--attest-trusted-origins", "--evaluated-at", T)
        assert code == 0, err
        lines = {line.split()[1]: line for line in out.splitlines()}
        assert "conflict=OPEN" in lines["P-prod-db-version"] and "acceptance=TENTATIVE" in lines["P-prod-db-version"]
        assert "acceptance=ACCEPTED" in lines["P-deploys-from-main"]
        assert "verification=NONE" in lines["P-api-key-rotated"]
        code, _, err = run("--db", db, EXAMPLE, "--attest-trusted-origins", "--evaluated-at", T)
        assert code == 0, "re-ingesting identical snapshots must be a no-op"
        with SQLiteAdapter(db) as store:
            listed = [p["proposition_id"] for p in store.list_propositions()]
        assert sorted(listed) == ["P-api-key-rotated", "P-deploys-from-main", "P-prod-db-version"], listed
    print("PASS ewp-ingest: trusted origins need attestation; example yields OPEN / ACCEPTED / NONE; re-ingest is a no-op")


def test_bad_input_is_reported_not_stored():
    with tempfile.TemporaryDirectory() as tmp:
        db = str(Path(tmp) / "ledger.sqlite")
        bad = Path(tmp) / "bad.json"
        view = json.loads(Path(EXAMPLE).read_text(encoding="utf-8"))["views"][2]
        view["subjects"] = "not-a-list"
        bad.write_text(json.dumps(view), encoding="utf-8")
        code, _, err = run("--db", db, str(bad))
        assert code == 1 and "must be a list of strings" in err, err
        with SQLiteAdapter(db) as store:
            assert store.list_propositions() == []
    print("PASS ewp-ingest: invalid view reported and not stored")


def test_bad_evaluated_at_stores_nothing():
    """A bad reporting time is refused before the ledger is opened: a failing
    exit must never leave views stored behind it."""
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "ledger.sqlite"
        code, out, err = run("--db", str(db), EXAMPLE, "--attest-trusted-origins", "--evaluated-at", "not-a-time")
        assert code == 2 and "nothing stored" in err and not out, (code, out, err)
        assert not db.exists(), "no ledger may be created"
    print("PASS ewp-ingest: bad --evaluated-at is refused before any write")


def main() -> int:
    test_quickstart_example()
    test_bad_input_is_reported_not_stored()
    test_bad_evaluated_at_stores_nothing()
    print("INGEST CLI SUITE PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
