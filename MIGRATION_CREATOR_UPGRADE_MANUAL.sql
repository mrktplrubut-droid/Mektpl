-- Manual Creator Upgrade
-- Jalankan sekali di PostgreSQL/Supabase.
-- Harga pembayaran dikontrol aplikasi melalui CREATOR_UPGRADE_PRICE.

CREATE TABLE IF NOT EXISTS creator_upgrade_payments (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL,
    amount BIGINT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending','approved','failed','cancelled')),
    admin_id BIGINT,
    created_at TIMESTAMP DEFAULT NOW(),
    paid_at TIMESTAMP,
    reviewed_at TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_creator_upgrade_user_status
ON creator_upgrade_payments(user_id, status);

CREATE INDEX IF NOT EXISTS idx_creator_upgrade_status_created
ON creator_upgrade_payments(status, created_at DESC);
