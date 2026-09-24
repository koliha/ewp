# EWP quickstart for testers

EWP-0.2.0. This gets you from a clone to Claude checking its remembered claims against evidence, using your own data.

The setup has two roles on purpose:

- **You** load evidence into a ledger (`ewp-ingest`). That is the ingest role.
- **Claude** reads the ledger through an MCP server (`ewp-mcp`) that cannot write. It can ask what is warranted; it cannot add or change evidence.

## 1. Install

Python 3.12 or newer.

```bash
git clone https://github.com/koliha/ewp.git
```

```bash
cd ewp && python -m pip install .
```

This installs two commands, `ewp-ingest` and `ewp-mcp`. (Or skip the install and use `python -m ewp.ingest_cli` / `python -m ewp.mcp_server` from the repository root.)

## 2. Try the example

```bash
ewp-ingest --db ledger.sqlite examples/quickstart.json --attest-trusted-origins
```

This creates `ledger.sqlite` in the repository directory. Note its absolute path for step 3.

You should see three propositions:

| Proposition | Result | Why |
|---|---|---|
| `P-prod-db-version` | `conflict=OPEN`, `acceptance=TENTATIVE` | The assistant *remembers* PostgreSQL 13 from a March conversation; a September `psql` check on `db-prod-1` says otherwise. |
| `P-deploys-from-main` | `acceptance=ACCEPTED`, `verification=EXTERNAL` | Read directly from the CI config by a tool. |
| `P-api-key-rotated` | `verification=NONE`, `acceptance=TENTATIVE` | Two memory summaries of the same stand-up notes. Repetition is one lineage, not confirmation. |

`--attest-trusted-origins` is you declaring that the `tool` records really came from tools. Without it, `ewp-ingest` stores only the views that have no trusted origins.

## 3. Connect Claude

Use an absolute path for `--db`. The agent-facing server has no `--allow-ingest`, so it is read-only.

**Claude Code:**

```bash
claude mcp add ewp -- ewp-mcp --db /absolute/path/to/ledger.sqlite
```

**Claude Desktop** (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "ewp": {
      "command": "ewp-mcp",
      "args": ["--db", "/absolute/path/to/ledger.sqlite"]
    }
  }
}
```

If the client cannot find `ewp-mcp`, give the full path (`which ewp-mcp` on macOS/Linux, `where ewp-mcp` on Windows).

Then ask something your memory covers, for example: *"Which PostgreSQL version is production on? Check EWP before answering."* Claude should find the proposition with `ewp_list_propositions`, call `ewp_memory_context`, and tell you the claim is disputed instead of repeating the remembered version.

For that claim you will see `verification=EXTERNAL` next to `conflict=OPEN`. `verification` says how strong the best check was, not which way it went: here a tool *checked and contradicted* the memory. `ewp_memory_context` adds a warning that the check opposes the claim.

A line you can add to your project instructions:

> Before relying on anything remembered from earlier sessions, look it up with `ewp_list_propositions` and `ewp_memory_context`. If `conflict=OPEN`, say so. If `acceptance` is not `ACCEPTED`, treat the claim as unverified.

## 4. Bring your own data

`ewp-ingest` takes a JSON file with one EvidenceView, a list, or `{"views": [...]}`. Copy a view from `examples/quickstart.json` and edit it. The full schema is `docs/implementer/SCHEMA.md`.

One view per claim (`proposition_id`). In each view:

| You have | Put it in | `origin_type` |
|---|---|---|
| Something the assistant said or remembered | `assertions` (+ `evidence` with `polarity`) | `turn` |
| A memory summary, extraction, or paraphrase | `assertions` / `evidence` | `summary` or `extract` |
| A tool, API, or command output that bears on the claim | `checks` with `result` `supports` / `opposes` / `inconclusive` | `tool` or `api` |
| A document you quoted | `checks` with `method: document_quote` | `document` |
| A person confirming it | `checks` with `method: human_attestation` | `human` |

Rules that matter most:

- **`lineage_id`** is "where did this originally come from". Give copies, summaries, and paraphrases of one source the same `lineage_id`, or repetition will look like independent confirmation.
- **Timestamps** are ISO 8601 with a timezone (`2026-09-20T09:00:00Z`). A record dated after the time you evaluate at is ignored for that evaluation.
- **`subjects`** (optional) names what the claim is about, e.g. `["db-prod-1"]`. If you set it, only checks naming the same subject can verify the claim.
- **Only `tool`, `document`, `human`, `api`, `vendor`, `sensor` origins can verify.** Anything the model produced itself (`turn`, `summary`, `extract`) never can, however confident it sounds. A trusted origin says where a check came from, not that the source is any good.
- **Leave out what you don't have.** If a conversation contains nothing worth keeping, ingest nothing for it. A missing record reads `UNACCEPTED`; a made-up one still counts as an assertion.
- **`origin_locator`** should let you find the exact passage again (a URL with `#page=`, a commit-pinned line range). See `docs/PLATFORMS.md`.

Updating a claim: ingest a new view for the same `proposition_id` containing everything that should be in it, with a new `view_id` (or no `view_id`: one is derived from the content). Earlier views stay readable by id; Claude sees the latest.

## Troubleshooting

| Message | Meaning |
|---|---|
| `needs --attest-trusted-origins` | The view has `tool`/`document`/… origins. Add the flag if that is true. |
| `EWP_REFUSE_MISSING_VIEW` | No such proposition in this ledger. Check `--db` and use `ewp_list_propositions`. |
| `is an immutable snapshot with different content` | You changed a view but kept its `view_id`. Use a new one. |
| `must be a list of strings`, `is not 'P-…'` | Input validation. `subjects` must be a list; every record in a view must be about that view's `proposition_id`. |
| `ledger not found` from `ewp-mcp` | The read-only server opens an existing ledger. Check the absolute `--db` path, or create it with `ewp-ingest`. |
| `--db is required` | The agent-facing server needs a ledger file. |
| `EWP_REFUSE_LEDGER_UNAVAILABLE`, `database is locked` | Another process held the ledger past the timeout, or the file is damaged. Retry; if it persists, check the file. |
| `ledger schema version … expected 4` | The ledger was created by an older development build. Start a new `--db` file. |
| `duplicate … id`, `carries different SourceRefs` | Each id may appear once per view, and one `source_id` must always describe the same source. |
| `EWP_REFUSE_INGEST_ROLE` from Claude | Expected: the agent-facing server is read-only. Load data with `ewp-ingest`. |

What the five axes mean, and why EWP refuses to collapse them into one "true/false": `README.md`. The MCP tools and error codes: `docs/MCP_CONTRACT.md`.
