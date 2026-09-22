# Security

EWP evaluates evidence. It does not authenticate callers, sign tokens, or authorize actions.

EWP assumes source-origin metadata presented in an `EvidenceView` has been authenticated or established by the trusted ingestion/adapter boundary. Untrusted agents must not be permitted to self-assert trusted `origin_type` values. EWP prevents epistemic laundering after ingestion; it does not itself authenticate evidence entering the ledger.

## What this project does not protect

- Agent tool execution
- Secret storage
- Prompt injection against an MCP client. `protocol.mcp_server` is an ingest boundary, not an authenticator; it refuses unattested trusted origins.
- Store credentials

Those belong in the platform (OpenClaw allowlists, Tenuo-style action warrants, ordinary IAM).

## What to report

- A path where endogenous processing (summarization, Dreaming, majority, Graphiti invalidation) can raise `verification` without new external evidence
- A path where compression or retrieval omits a contradictor without `sufficiency=DEGRADED`
- A path where `may_act` can be skipped or inferred from `WarrantView` alone
- Supply-chain issues in this repository

Open an issue marked `security` or contact Rob Koliha privately if you have an unfixed write-up. There is no bug bounty attached to this freeze.
