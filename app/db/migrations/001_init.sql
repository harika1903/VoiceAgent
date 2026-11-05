-- System of record (architecture §5.2). Redis holds hot/ephemeral call state;
-- everything durable lives here. Writers: Backend (orgs/keys/agents),
-- Dispatcher (call_sessions), Post-Call Processor (turns/recordings/usage/summary).

CREATE TABLE orgs (
    id                    TEXT PRIMARY KEY,
    name                  TEXT NOT NULL,
    max_concurrent_calls  INTEGER,                 -- NULL = use the global default
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE api_keys (
    id          BIGSERIAL PRIMARY KEY,
    org_id      TEXT NOT NULL REFERENCES orgs(id),
    key_hash    TEXT NOT NULL UNIQUE,              -- sha256 of the key; the key is never stored
    label       TEXT NOT NULL DEFAULT '',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    revoked_at  TIMESTAMPTZ
);

CREATE TABLE agents (
    org_id          TEXT NOT NULL REFERENCES orgs(id),
    id              TEXT NOT NULL,
    current_version INTEGER NOT NULL,
    deleted_at      TIMESTAMPTZ,                   -- soft delete: blocks NEW sessions only
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (org_id, id)
);

-- Immutable history: a call can always be replayed against the exact config it used.
CREATE TABLE agent_versions (
    org_id      TEXT NOT NULL,
    agent_id    TEXT NOT NULL,
    version     INTEGER NOT NULL,
    config      JSONB NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (org_id, agent_id, version),
    FOREIGN KEY (org_id, agent_id) REFERENCES agents(org_id, id)
);

CREATE TABLE call_sessions (
    id            TEXT PRIMARY KEY,
    org_id        TEXT NOT NULL REFERENCES orgs(id),
    agent_id      TEXT NOT NULL,
    agent_version INTEGER NOT NULL,
    call_type     TEXT NOT NULL,                   -- web_inbound | pstn_inbound | pstn_outbound
    status        TEXT NOT NULL,
    epoch         INTEGER NOT NULL DEFAULT 0,
    room          TEXT,
    worker_id     TEXT,
    end_reason    TEXT,
    created_at    TIMESTAMPTZ NOT NULL,
    started_at    TIMESTAMPTZ,
    ended_at      TIMESTAMPTZ,
    duration_secs DOUBLE PRECISION,
    summary       TEXT,                            -- written by Post-Call
    post_call_at  TIMESTAMPTZ                      -- set once Post-Call has fully persisted
);
CREATE INDEX call_sessions_org_created ON call_sessions (org_id, created_at DESC);

CREATE TABLE transcript_turns (
    session_id  TEXT NOT NULL REFERENCES call_sessions(id) ON DELETE CASCADE,
    seq         INTEGER NOT NULL,
    role        TEXT NOT NULL,
    text        TEXT NOT NULL,
    at          TIMESTAMPTZ NOT NULL,
    interrupted BOOLEAN NOT NULL DEFAULT false,
    PRIMARY KEY (session_id, seq)
);

-- Pointers to files in object storage (transcript JSON now; audio recording when Egress lands).
CREATE TABLE session_artifacts (
    session_id  TEXT NOT NULL REFERENCES call_sessions(id) ON DELETE CASCADE,
    kind        TEXT NOT NULL,                     -- transcript_json | recording
    object_key  TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (session_id, kind)
);

-- One row per session per kind => reconciliation is idempotent (safe to re-run).
CREATE TABLE usage_records (
    session_id  TEXT NOT NULL REFERENCES call_sessions(id) ON DELETE CASCADE,
    org_id      TEXT NOT NULL,
    kind        TEXT NOT NULL,                     -- call_seconds | stt_seconds | llm_tokens | tts_chars
    quantity    DOUBLE PRECISION NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (session_id, kind)
);
