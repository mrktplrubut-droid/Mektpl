-- PAS TELE SHARE UNLOCK + TELEGRAM SAFETY
-- Safe to run repeatedly on Supabase/PostgreSQL.

BEGIN;

CREATE TABLE IF NOT EXISTS code_share_progress (
    id BIGSERIAL PRIMARY KEY,
    code TEXT NOT NULL,
    user_id BIGINT NOT NULL,
    target INT NOT NULL DEFAULT 1,
    progress INT NOT NULL DEFAULT 0,
    is_paid BOOLEAN NOT NULL DEFAULT FALSE,
    completed BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(code,user_id)
);

CREATE TABLE IF NOT EXISTS code_share_events (
    id BIGSERIAL PRIMARY KEY,
    code TEXT NOT NULL,
    owner_id BIGINT NOT NULL,
    new_member_id BIGINT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(code,owner_id,new_member_id)
);

CREATE INDEX IF NOT EXISTS idx_code_share_progress_user
    ON code_share_progress(user_id);
CREATE INDEX IF NOT EXISTS idx_code_share_progress_code
    ON code_share_progress(code);
CREATE INDEX IF NOT EXISTS idx_code_share_events_owner
    ON code_share_events(owner_id);
CREATE INDEX IF NOT EXISTS idx_code_share_events_member
    ON code_share_events(new_member_id);

-- Runtime settings used by the admin safety panel.
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);

INSERT INTO settings(key,value) VALUES
 ('telegram_user_send_delay','3'),
 ('telegram_storage_delay','1'),
 ('telegram_channel_delay','1'),
 ('telegram_storage_concurrency','1'),
 ('telegram_safety_enabled','on')
ON CONFLICT(key) DO NOTHING;

COMMIT;
