# Security

EWP evaluates evidence. It does not authenticate callers, sign tokens, or authorize actions.

EWP assumes source-origin metadata presented in an `EvidenceView` has been authenticated or established by the trusted ingestion/adapter boundary. Untrusted agents must not be permitted to self-assert trusted `origin_type` values. EWP prevents epistemic laundering after ingestion; it does not itself authenticate evidence entering the ledger.

## What this project does not protect

- Agent tool execution
- Secret storage
- Prompt injection against an MCP client. `ewp.mcp_server` is an ingest boundary, not an authenticator. Every write requires a server-side ingest role (`--allow-ingest` on stdio, the ingest token on HTTP); without it the server is evaluate-only. `ingest_attestation` is not a credential.
- The HTTP façade (`POST /mcp`) has no TLS and no origin check. Bind it to loopback. Supply the ingest token through `EWP_INGEST_TOKEN` or `--ingest-token-file`, not the command line.
- Caller-built evidence. An inline `EvidenceView` sent to `ewp_warrant_now` has its trusted origins demoted; `ewp_may_act` refuses inline views and evaluates stored evidence at server time.
- Store credentials

Those belong in the platform (OpenClaw allowlists, Tenuo-style action warrants, ordinary IAM).

## What to report

- A path where endogenous processing (summarization, Dreaming, majority, Graphiti invalidation) can raise `verification` without new external evidence
- A path where compression or retrieval omits a contradictor without `sufficiency=DEGRADED`
- A path where `may_act` can be skipped or inferred from `WarrantView` alone
- A write path that changes a stored record, conflict participants, or view completeness without the ingest role
- An input value outside a closed enum that is evaluated instead of refused
- An adapter that loses a field (`subjects[]`, polarity, timestamps, completeness) and changes the axes on round trip
- Supply-chain issues in this repository

Open an issue marked `security` or contact Rob Koliha privately if you have an unfixed write-up. There is no bug bounty attached to this release.
