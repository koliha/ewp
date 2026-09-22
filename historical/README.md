# Historical sketches — not the v0.1 freeze

These files belong to an earlier “warrantmem” design: a Postgres claim ledger, MCP write façade, and confidence caps on `claim_status`.

They are kept so the design trail is inspectable. They are **not** the Epistemic Warrant Protocol.

Normative for v0.1.0:

- `protocol/` — kernel, types, adapters, fixtures
- `tests/` — conformance and goldens
- `docs/PROTOCOL_v0.1.md`, `docs/DESIGN_NOTE.md`, `docs/implementer/`
- `docs/PLATFORMS.md` — integration notes; treat MCP tool names there as planned, not shipped

Do not implement `claims.status = current` as stored epistemic truth. Warrant is computed.

`SESSION_HANDOFF.json` is an internal working note, not protocol text.
