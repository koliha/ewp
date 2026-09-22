# Third-implementation pack

You are asked to implement:

```
warrant_now(view, policy, evaluated_at) -> five axes
```

You are given this directory only: schema, policy prose (`POLICY.md`, `policy.json`), fixture JSON, expected five-axis JSON. Policy id and version are `reference-v1`. Check `result` and source `origin_type` are required inputs.

You are not given `protocol/warrant.py`, `protocol/warrant_b.py`, helper names, or the repository test assertions.

`third_eval.py` in this directory is a clean evaluator: policy.json + fixture JSON only, no `protocol.*` imports. Gate: `python3 docs/implementer/third_eval.py`.

## What conformance means

Conformance is defined over the normative WarrantView axes, not over reference-policy convenience fields.

Axes: `acceptance`, `conflict`, `verification`, `currency`, `sufficiency`.

If you emit a scalar `strength`, ignore it when comparing. The expected files do not contain it.

## How to run your comparison

For each file in `fixtures/`:

1. Read the view and the sibling `evaluated_at` field in that JSON.
2. Apply `policy.json` / `POLICY.md`.
3. Compare your five axes to `expected/<same-name>.json`.

Report a table:

```
fixture                 yours        expected     class
---------------------------------------------------------
launder_verification    INDIRECT     INDIRECT     —
08-verified-stale       STALE        STALE        —
…                       TENTATIVE    ACCEPTED     spec | policy | impl
```

Class a disagreement as:

- **spec** — the prose in this pack can reasonably be read your way
- **policy** — the prose is clear; you think the judgment is wrong
- **impl** — the prose is clear; your code missed it

Do not “fix” expected outputs to match your code.
