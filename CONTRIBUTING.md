# Contributing

EWP-0.2.0 is locked by `RELEASE.lock.json` under policy `reference-v2`. Most useful work is adapters, tests, and documentation — not ontology.

## What to change

| Change | How |
|---|---|
| Adapter bug | Fix the adapter. Do not edit goldens. `tests/test_adapter_roundtrip.py` must pass for every fixture. |
| Missing ugly case | Add a fixture to the hardening pack (`protocol/laundering.py`). If it needs a new judgment, that is a policy change. |
| Policy judgment changes | Mint a new policy name (`reference-v3`). A policy name never changes meaning. |
| Golden, pack, or evaluator drift | Requires an explicit version change, then `python3 tests/write_goldens.py`, `python3 tests/export_implementer_pack.py`, `python3 tests/ci.py --write-lock`. Review every golden diff. |
| Store wants a different answer | That is `NONCONFORMANT`, not a README patch. |

Rule: stores adapt to the protocol. The protocol does not inherit the store’s epistemology.

## Checks

```bash
python3 tests/ci.py
python3 tests/report.py
```

Python 3.12+ is what the reference tree is run on. `pip install mcp` enables the official-SDK interop test in `tests/test_mcp.py`; it is skipped otherwise.

## Pull requests

- One concern per PR.
- Do not silently refresh `tests/golden_warrantviews/`, `docs/implementer/expected/`, or `RELEASE.lock.json`.
- Do not change `protocol/classify.py` / `protocol/warrant.py` without regenerating goldens *and* changing the policy or protocol version.
- Keep `docs/implementer/third_eval.py` independent: it reads only `docs/implementer/`.
- Do not fold `may_act` into `warrant_now`.
- Name the project **EWP** in user-facing text. Keep `warrant_now` / `WarrantView` as kernel verbs.

Copyright © 2026 Rob Koliha.
