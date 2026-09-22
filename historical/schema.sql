-- EWP v0 schema (PostgreSQL 16+)
-- Append-only events. Claims are versioned by supersession, never silently overwritten.
-- Confidence lives on warrant, not on proposition text.

CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
-- Optional later: CREATE EXTENSION IF NOT EXISTS vector;

CREATE TYPE claim_type AS ENUM (
  'observation',
  'inference',
  'report',
  'convention',
  'procedure'
);

CREATE TYPE claim_status AS ENUM (
  'proposed',
  'current',
  'disputed',
  'stale',
  'superseded',
  'retracted'
);

CREATE TYPE event_kind AS ENUM (
  'utterance',
  'tool_call',
  'tool_result',
  'document',
  'external_check',
  'session_open',
  'session_close',
  'branch',
  'merge',
  'compression',
  'system'
);

CREATE TYPE verification_method AS ENUM (
  'none',
  'external_clock',
  'tool_observation',
  'human_attestation',
  'independent_reproduction',
  'document_quote',
  'model_introspection' -- lowest grade; cannot raise confidence above proposed
);

CREATE TABLE nodes (
  node_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  lineage_id     TEXT NOT NULL,
  branch_id      TEXT NOT NULL,
  parent_node_ids UUID[] NOT NULL DEFAULT '{}',
  agent_label    TEXT,
  model_label    TEXT,
  started_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  ended_at       TIMESTAMPTZ,
  notes          TEXT
);

CREATE TABLE events (
  event_id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  node_id        UUID NOT NULL REFERENCES nodes(node_id),
  kind           event_kind NOT NULL,
  recorded_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  occurred_at    TIMESTAMPTZ,          -- world time; may be null if unknown
  occurred_at_source TEXT,             -- 'host_clock' | 'model_claimed' | 'document' | 'unknown'
  payload        JSONB NOT NULL,
  parent_event_ids UUID[] NOT NULL DEFAULT '{}',
  content_hash   TEXT
);

CREATE INDEX events_node_recorded_idx ON events (node_id, recorded_at);
CREATE INDEX events_kind_idx ON events (kind);

CREATE TABLE claims (
  claim_id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  lineage_id          TEXT NOT NULL,
  branch_id           TEXT NOT NULL,
  proposition         TEXT NOT NULL,
  scope               TEXT,
  originating_node    UUID NOT NULL REFERENCES nodes(node_id),
  originating_event   UUID REFERENCES events(event_id),
  parent_claim_ids    UUID[] NOT NULL DEFAULT '{}',
  claim_type          claim_type NOT NULL,
  status              claim_status NOT NULL DEFAULT 'proposed',
  valid_from          TIMESTAMPTZ,
  valid_until         TIMESTAMPTZ,
  learned_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_verified_at    TIMESTAMPTZ,
  verification_method verification_method NOT NULL DEFAULT 'none',
  falsification_condition TEXT,
  confidence_basis    TEXT NOT NULL,
  confidence          NUMERIC(4,3) NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
  expiry_policy       JSONB,
  graphiti_episode_uuid TEXT,
  created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX claims_lineage_status_idx ON claims (lineage_id, status);
CREATE INDEX claims_proposition_trgm ON claims USING gin (proposition gin_trgm_ops);

-- Confidence may never increase except via a verification event.
-- Enforced in application layer + this history table.

CREATE TABLE claim_mutations (
  mutation_id    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  claim_id       UUID NOT NULL REFERENCES claims(claim_id),
  event_id       UUID NOT NULL REFERENCES events(event_id),
  actor_node     UUID NOT NULL REFERENCES nodes(node_id),
  op             TEXT NOT NULL, -- propose | verify | dispute | supersede | retract | expire | compress
  before         JSONB NOT NULL,
  after          JSONB NOT NULL,
  confidence_before NUMERIC(4,3) NOT NULL,
  confidence_after  NUMERIC(4,3) NOT NULL,
  CHECK (
    op = 'verify'
    OR confidence_after <= confidence_before
  ),
  recorded_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE evidence_refs (
  claim_id       UUID NOT NULL REFERENCES claims(claim_id),
  event_id       UUID REFERENCES events(event_id),
  graphiti_edge_uuid TEXT,
  uri            TEXT,
  quote          TEXT,
  note           TEXT,
  PRIMARY KEY (claim_id, COALESCE(event_id, '00000000-0000-0000-0000-000000000000'::uuid), COALESCE(uri, ''))
);

CREATE TABLE contradictions (
  contradiction_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  claim_a          UUID NOT NULL REFERENCES claims(claim_id),
  claim_b          UUID NOT NULL REFERENCES claims(claim_id),
  status           TEXT NOT NULL DEFAULT 'open', -- open | resolved | withdrawn
  resolving_claim  UUID REFERENCES claims(claim_id),
  resolving_event  UUID REFERENCES events(event_id),
  note             TEXT,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  CHECK (claim_a <> claim_b)
);

CREATE TABLE supersessions (
  old_claim_id   UUID NOT NULL REFERENCES claims(claim_id),
  new_claim_id   UUID NOT NULL REFERENCES claims(claim_id),
  event_id       UUID NOT NULL REFERENCES events(event_id),
  PRIMARY KEY (old_claim_id, new_claim_id)
);

CREATE TABLE persona_snapshots (
  snapshot_id    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  lineage_id     TEXT NOT NULL,
  branch_id      TEXT NOT NULL,
  generated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  generated_from_claim_ids UUID[] NOT NULL,
  briefing       TEXT NOT NULL,
  token_count    INT,
  expires_at     TIMESTAMPTZ
);

-- Epistemic checksum: enough structure to know how a compressed claim could die.
CREATE OR REPLACE FUNCTION claim_checksum(c claims)
RETURNS TEXT LANGUAGE sql IMMUTABLE AS $$
  SELECT md5(
    concat_ws('|',
      c.claim_id::text,
      c.claim_type::text,
      c.status::text,
      COALESCE(c.verification_method::text, ''),
      COALESCE(c.last_verified_at::text, ''),
      COALESCE(c.falsification_condition, ''),
      c.confidence_basis,
      c.confidence::text
    )
  );
$$;
