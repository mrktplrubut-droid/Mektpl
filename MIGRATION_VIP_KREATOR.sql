-- PasTele VIP / Kreator migration
-- Aman dijalankan pada database PostgreSQL/Supabase yang sudah ada.
-- Tidak DROP/rename kolom/tabel lama.

CREATE TABLE IF NOT EXISTS premium_payments (
    id SERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL,
    package_id TEXT NOT NULL,
    amount BIGINT NOT NULL,
    payment_id TEXT UNIQUE NOT NULL,
    status TEXT DEFAULT 'pending',
    qr_string TEXT,
    payment_url TEXT,
    expires_at TIMESTAMP,
    access_until TIMESTAMP,
    code_limit INT DEFAULT 0,
    paid_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS premium_code_usage (
    user_id BIGINT NOT NULL,
    code TEXT NOT NULL,
    payment_id TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    PRIMARY KEY (user_id, code)
);

ALTER TABLE users ADD COLUMN IF NOT EXISTS is_creator BOOLEAN DEFAULT FALSE;
ALTER TABLE users ADD COLUMN IF NOT EXISTS creator_status TEXT DEFAULT 'none';
ALTER TABLE users ADD COLUMN IF NOT EXISTS creator_verified_at TIMESTAMP;
ALTER TABLE users ADD COLUMN IF NOT EXISTS vip BOOLEAN DEFAULT FALSE;
ALTER TABLE users ADD COLUMN IF NOT EXISTS is_vip BOOLEAN DEFAULT FALSE;
ALTER TABLE users ADD COLUMN IF NOT EXISTS vip_until TIMESTAMP;
ALTER TABLE users ADD COLUMN IF NOT EXISTS vip_expired TIMESTAMP;
ALTER TABLE users ADD COLUMN IF NOT EXISTS plan TEXT DEFAULT 'free';
ALTER TABLE users ADD COLUMN IF NOT EXISTS expired_at TIMESTAMP;

CREATE INDEX IF NOT EXISTS idx_premium_payments_user_status
ON premium_payments(user_id, status);

CREATE INDEX IF NOT EXISTS idx_premium_code_usage_user
ON premium_code_usage(user_id);
