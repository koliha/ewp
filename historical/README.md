# Historical sketches — not the v0.1 freeze

These files belong to an earlier “warrantmem” design: a Postgres claim ledger, MCP write façade, and confidence caps on `claim_status`.

They are kept so the design trail is inspectable. They are **not** the Epistemic Warrant Protocol.

Normative for v0.1.0:

- `protocol/` — kernel, types, adapters, fixtures
- `tests/` — conformance and goldens
- `docs/PROTOCOL_v0.1.md`, `docs/DESIGN_NOTE.md`, `docs/implementer/`
- `docs/PLATFORMS.md` — integration notes; treat MCP tool names there as planned, not shipped

Historical, not the freeze:

- `historical/docs/MCP_CONTRACT.md` — MCP tool-contract sketch
- `docs/MCP_CONTRACT.md` — pointer only, so old `docs/MCP_CONTRACT.md` links resolve here
- `historical/src/ledger.py`, `historical/schema.sql`, `historical/docker-compose.yml` — warrantmem ledger sketches
- `historical/SESSION_HANDOFF.json` — internal working note, not protocol text

Do not implement `claims.status = current` as stored epistemic truth. Warrant is computed.
