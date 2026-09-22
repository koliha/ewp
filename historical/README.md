# Historical sketches — not the current protocol

These files belong to an earlier “warrantmem” design: a Postgres claim ledger, MCP write façade, and confidence caps on `claim_status`.

They are kept so the design trail is inspectable. They are **not** the Epistemic Warrant Protocol.

Normative for EWP-0.2.0 (policy `reference-v1`):

- `protocol/` — kernel, types, adapters, fixtures, MCP server
- `tests/` — conformance, goldens, live mappings, MCP façade
- `docs/PROTOCOL_v0.1.md` — current conceptual contract (v0.2 text; filename kept for links)
- `docs/DESIGN_NOTE.md`, `docs/implementer/`, `docs/PLATFORMS.md`
- `docs/MCP_CONTRACT.md` — shipped MCP façade (`python3 -m protocol.mcp_server`)

Historical, not the protocol:

- `historical/docs/MCP_CONTRACT.md` — pre-freeze claim/confidence sketch (superseded)
- `historical/src/ledger.py`, `historical/schema.sql`, `historical/docker-compose.yml` — warrantmem ledger sketches
- `historical/SESSION_HANDOFF.json` — internal working note, not protocol text

Do not implement `claims.status = current` as stored epistemic truth. Warrant is computed.
