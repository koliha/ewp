# Contributing

EWP v0.1.0 is frozen. Most useful work is adapters, tests, and documentation — not ontology.

## What to change

| Change | How |
|---|---|
| Adapter bug | Fix the adapter. Do not edit goldens. |
| Missing ugly case | Add a fixture *and* a protocol/policy bump if the contract must grow. |
| Golden or evaluator drift | Requires an explicit version bump, then `python3 tests/ci.py --write-lock`. |
| Store wants a different answer | That is `NONCONFORMANT`, not a README patch. |

Rule: stores adapt to the protocol. The protocol does not inherit the store’s epistemology.

## Checks

```bash
python3 tests/ci.py
python3 tests/report.py
```

Python 3.12+ is what the reference tree is run on.

## Pull requests

- One concern per PR.
- Do not silently refresh `tests/golden_warrantviews/` or `RELEASE.lock.json`.
- Do not change `protocol/classify.py` / `protocol/warrant.py` without regenerating goldens *and* bumping policy or protocol.
- Do not fold `may_act` into `warrant_now`.
- Name the project **EWP** in user-facing text. Keep `warrant_now` / `WarrantView` as kernel verbs.

Copyright © 2026 Rob Koliha.
