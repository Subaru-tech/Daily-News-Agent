-- Daily News Agent — Database Schema

CREATE TABLE IF NOT EXISTS claims (
    id              SERIAL PRIMARY KEY,
    title           TEXT NOT NULL,
    url             TEXT NOT NULL,
    url_hash        TEXT NOT NULL,
    summary         TEXT DEFAULT '',
    category        TEXT DEFAULT 'General',
    confidence      INTEGER DEFAULT 0,
    verification_status TEXT DEFAULT 'unverified',  -- unverified, verified, disputed, debunked
    sources_json    TEXT DEFAULT '[]',
    calendar_event_id TEXT DEFAULT NULL,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    morning_sent    BOOLEAN DEFAULT FALSE,
    evening_sent    BOOLEAN DEFAULT FALSE,
    breaking_sent   BOOLEAN DEFAULT FALSE,
    debunked        BOOLEAN DEFAULT FALSE,
    debunked_note   TEXT DEFAULT NULL,
    reasoning       TEXT DEFAULT '',
    tickers_json    TEXT DEFAULT '[]',
    price_data_json TEXT DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_claims_url_hash ON claims(url_hash);
CREATE INDEX IF NOT EXISTS idx_claims_created_at ON claims(created_at);
CREATE INDEX IF NOT EXISTS idx_claims_category ON claims(category);

CREATE TABLE IF NOT EXISTS verification_cache (
    claim_hash      TEXT PRIMARY KEY,
    result_json     TEXT NOT NULL,
    verified_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS api_quotas (
    api_name        TEXT PRIMARY KEY,
    calls_used      INTEGER DEFAULT 0,
    resets_at       TIMESTAMP NOT NULL
);
