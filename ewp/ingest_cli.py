"""ewp-ingest — load EvidenceViews from JSON into an EWP SQLite ledger.

This is the ingest pipeline for someone with file access to the ledger:
the operator, not the agent. The agent-facing MCP server can then run
read-only (`ewp-mcp --db <same file>`, no --allow-ingest).

Input: a JSON file holding one EvidenceView object, a list of them, or
{"views": [...]}. Each view is validated and stored as an immutable
snapshot. Views naming a trusted origin_type (tool, document, human, api,
vendor, sensor) are refused unless --attest-trusted-origins is given:
that flag is you declaring those origins were established outside the agent.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .classify import InvalidEvidenceView
from .codec import view_from_dict
from .sqlite_adapter import ImmutableRecordError, LedgerError, SQLiteAdapter
from .types import TRUSTED_ORIGINS, EvidenceView, Policy
from .warrant import warrant_now


def _views_in(payload: Any) -> list[dict]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict) and isinstance(payload.get("views"), list):
        return payload["views"]
    if isinstance(payload, dict):
        return [payload]
    raise ValueError("expected an EvidenceView object, a list of them, or {\"views\": [...]}")


def _trusted_origins(view: EvidenceView) -> set[str]:
    found = {a.source.origin_type for a in view.assertions}
    found |= {e.source.origin_type for e in view.evidence}
    found |= {c.source.origin_type for c in view.checks}
    return found & set(TRUSTED_ORIGINS)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ewp-ingest", description=__doc__.split("\n\n")[0])
    parser.add_argument("files", nargs="+", help="JSON files of EvidenceViews")
    parser.add_argument("--db", required=True, help="SQLite ledger path (created if missing)")
    parser.add_argument(
        "--attest-trusted-origins",
        action="store_true",
        help="declare that tool/document/human/api/vendor/sensor origins in these files were established outside the agent",
    )
    parser.add_argument("--evaluated-at", default="", help="report warrant at this instant (default: now, UTC)")
    args = parser.parse_args(argv)

    Path(args.db).parent.mkdir(parents=True, exist_ok=True)
    try:
        store = SQLiteAdapter(args.db)
    except LedgerError as exc:
        print(f"ewp-ingest: {exc}", file=sys.stderr)
        return 2
    with store:
        return _ingest(store, args)


def _ingest(store: SQLiteAdapter, args: argparse.Namespace) -> int:
    evaluated_at = args.evaluated_at or datetime.now(timezone.utc).isoformat()
    failures = 0
    for file in args.files:
        try:
            raws = _views_in(json.loads(Path(file).read_text(encoding="utf-8")))
        except (OSError, ValueError) as exc:
            print(f"FAIL {file}: {exc}", file=sys.stderr)
            failures += 1
            continue
        for i, raw in enumerate(raws):
            label = f"{file}[{i}]"
            try:
                view = view_from_dict(raw)
                trusted = _trusted_origins(view)
                if trusted and not args.attest_trusted_origins:
                    raise PermissionError(
                        f"trusted origin_type {sorted(trusted)} needs --attest-trusted-origins "
                        "(you are declaring these were observed outside the agent)"
                    )
                store.load_view(view)
                w = warrant_now(view, Policy(), evaluated_at).warrant
            except (InvalidEvidenceView, ImmutableRecordError, PermissionError, KeyError, TypeError, ValueError, sqlite3.Error) as exc:
                reason = f"missing field {exc}" if isinstance(exc, KeyError) else str(exc)
                print(f"FAIL {label}: {reason}", file=sys.stderr)
                failures += 1
                continue
            print(
                f"stored {view.proposition_id} view={view.view_id}  "
                f"acceptance={w.acceptance} conflict={w.conflict} verification={w.verification} "
                f"currency={w.currency} sufficiency={w.sufficiency}"
            )
    if failures:
        print(f"{failures} view(s) not stored", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
