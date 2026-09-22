# MCP contract — moved

The v0.1.0 freeze does **not** ship an MCP server. The tool-contract sketch
that used to live here is historical, not normative.

**Canonical location:** [`historical/docs/MCP_CONTRACT.md`](../historical/docs/MCP_CONTRACT.md)

That sketch describes a planned `ewp.mcp` façade (`memory_context`,
`claim_propose`, `check_record`, …). It is not required to evaluate warrant.
`warrant_now()` is the frozen kernel.

Platform integration notes that *refer* to the sketch:

- `docs/PLATFORMS.md` — OpenClaw / Claude / Codex wiring; server is planned, not shipped
- `docs/implementer/LIVE_ADAPTERS.md` — live Graphiti and Mem0 store mappings (also not an MCP server)

Do not implement `historical/docs/MCP_CONTRACT.md` as if it were the protocol.
