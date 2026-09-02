-- ============================================================
-- MEKTPL / MARKETPLACE FINAL DATABASE SCHEMA
-- PostgreSQL / Supabase / Railway compatible
-- Safe to run on an existing installation.
-- ============================================================

CREATE TABLE IF NOT EXISTS users (
    user_id BIGINT PRIMARY KEY,
    username TEXT,
    fullname TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    is_banned BOOLEAN DEFAULT FALSE,
    is_admin BOOLEAN DEFAULT FALSE,
    chat_id BIGINT,
    full_name TEXT,
    last_seen TIMESTAMP,
    balance BIGINT DEFAULT 0,
    total_earn BIGINT DEFAULT 0,
    total_referral BIGINT DEFAULT 0,
    referral_count BIGINT DEFAULT 0,
    ref_10_claimed BOOLEAN DEFAULT FALSE,
    ref_20_claimed BOOLEAN DEFAULT FALSE,
    ref_50_claimed BOOLEAN DEFAULT FALSE,
    referred_by BIGINT,
    is_creator BOOLEAN DEFAULT FALSE,
    creator_status TEXT DEFAULT 'none',
    creator_verified_at TIMESTAMP,
    phone TEXT,
    creator_telegram TEXT,
    updated_at TIMESTAMP DEFAULT NOW(),
    vip BOOLEAN DEFAULT FALSE,
    is_vip BOOLEAN DEFAULT FALSE,
    vvip BOOLEAN DEFAULT FALSE,
    is_vvip BOOLEAN DEFAULT FALSE,
    plan TEXT DEFAULT 'free',
    vip_until TIMESTAMP,
    vip_expired TIMESTAMP,
    vvip_until TIMESTAMP,
    vvip_expired TIMESTAMP,
    expired_at TIMESTAMP,
    language TEXT DEFAULT 'id',
    free_share_count INT DEFAULT 0,
    paid_quota INT DEFAULT 0,
    total_withdraw BIGINT DEFAULT 0
);

ALTER TABLE users ADD COLUMN IF NOT EXISTS chat_id BIGINT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS full_name TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS fullname TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS balance BIGINT DEFAULT 0;
ALTER TABLE users ADD COLUMN IF NOT EXISTS total_earn BIGINT DEFAULT 0;
ALTER TABLE users ADD COLUMN IF NOT EXISTS total_referral BIGINT DEFAULT 0;
ALTER TABLE users ADD COLUMN IF NOT EXISTS referral_count BIGINT DEFAULT 0;
ALTER TABLE users ADD COLUMN IF NOT EXISTS is_creator BOOLEAN DEFAULT FALSE;
ALTER TABLE users ADD COLUMN IF NOT EXISTS creator_status TEXT DEFAULT 'none';
ALTER TABLE users ADD COLUMN IF NOT EXISTS creator_verified_at TIMESTAMP;
ALTER TABLE users ADD COLUMN IF NOT EXISTS language TEXT DEFAULT 'id';
ALTER TABLE users ADD COLUMN IF NOT EXISTS total_withdraw BIGINT DEFAULT 0;
ALTER TABLE users ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT NOW();
UPDATE users SET chat_id = user_id WHERE chat_id IS NULL;
UPDATE users SET full_name = COALESCE(full_name, fullname) WHERE full_name IS NULL;
UPDATE users SET fullname = COALESCE(fullname, full_name) WHERE fullname IS NULL;

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);
INSERT INTO settings(key,value) VALUES ('maintenance','off') ON CONFLICT(key) DO NOTHING;

CREATE TABLE IF NOT EXISTS wallets (
    user_id BIGINT PRIMARY KEY,
    balance BIGINT DEFAULT 0
);

CREATE TABLE IF NOT EXISTS files (
    code TEXT PRIMARY KEY,
    title TEXT,
    creator TEXT,
    media TEXT,
    share_media TEXT,
    is_share BOOLEAN DEFAULT FALSE,
    owner_id BIGINT,
    seller_id BIGINT,
    media_count INT DEFAULT 0,
    expires_at TIMESTAMP,
    is_paid BOOLEAN DEFAULT FALSE,
    price BIGINT DEFAULT 0,
    payment_provider TEXT,
    review_photos TEXT,
    view_count BIGINT DEFAULT 0,
    download_count BIGINT DEFAULT 0,
    favorite_count BIGINT DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW(),
    description TEXT,
    category TEXT,
    tags TEXT,
    syntax TEXT,
    visibility TEXT DEFAULT 'public',
    slug TEXT,
    market_server TEXT DEFAULT '1',
    views BIGINT DEFAULT 0,
    sold BIGINT DEFAULT 0,
    buy_count BIGINT DEFAULT 0,
    likes BIGINT DEFAULT 0,
    dislikes BIGINT DEFAULT 0,
    rating NUMERIC(3,1) DEFAULT 0,
    review_count BIGINT DEFAULT 0,
    free_progress INT DEFAULT 0,
    free_unlock_enabled BOOLEAN DEFAULT TRUE
);

ALTER TABLE files ADD COLUMN IF NOT EXISTS title TEXT;
ALTER TABLE files ADD COLUMN IF NOT EXISTS creator TEXT;
ALTER TABLE files ADD COLUMN IF NOT EXISTS media TEXT;
ALTER TABLE files ADD COLUMN IF NOT EXISTS share_media TEXT;
ALTER TABLE files ADD COLUMN IF NOT EXISTS is_share BOOLEAN DEFAULT FALSE;
ALTER TABLE files ADD COLUMN IF NOT EXISTS owner_id BIGINT;
ALTER TABLE files ADD COLUMN IF NOT EXISTS seller_id BIGINT;
ALTER TABLE files ADD COLUMN IF NOT EXISTS media_count INT DEFAULT 0;
ALTER TABLE files ADD COLUMN IF NOT EXISTS expires_at TIMESTAMP;
ALTER TABLE files ADD COLUMN IF NOT EXISTS is_paid BOOLEAN DEFAULT FALSE;
ALTER TABLE files ADD COLUMN IF NOT EXISTS price BIGINT DEFAULT 0;
ALTER TABLE files ADD COLUMN IF NOT EXISTS payment_provider TEXT;
ALTER TABLE files ADD COLUMN IF NOT EXISTS review_photos TEXT;
ALTER TABLE files ADD COLUMN IF NOT EXISTS view_count BIGINT DEFAULT 0;
ALTER TABLE files ADD COLUMN IF NOT EXISTS download_count BIGINT DEFAULT 0;
ALTER TABLE files ADD COLUMN IF NOT EXISTS favorite_count BIGINT DEFAULT 0;
ALTER TABLE files ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT NOW();
ALTER TABLE files ADD COLUMN IF NOT EXISTS description TEXT;
ALTER TABLE files ADD COLUMN IF NOT EXISTS category TEXT;
ALTER TABLE files ADD COLUMN IF NOT EXISTS tags TEXT;
ALTER TABLE files ADD COLUMN IF NOT EXISTS syntax TEXT;
ALTER TABLE files ADD COLUMN IF NOT EXISTS visibility TEXT DEFAULT 'public';
ALTER TABLE files ADD COLUMN IF NOT EXISTS slug TEXT;
ALTER TABLE files ADD COLUMN IF NOT EXISTS market_server TEXT DEFAULT '1';
ALTER TABLE files ADD COLUMN IF NOT EXISTS views BIGINT DEFAULT 0;
ALTER TABLE files ADD COLUMN IF NOT EXISTS sold BIGINT DEFAULT 0;
ALTER TABLE files ADD COLUMN IF NOT EXISTS buy_count BIGINT DEFAULT 0;
ALTER TABLE files ADD COLUMN IF NOT EXISTS likes BIGINT DEFAULT 0;
ALTER TABLE files ADD COLUMN IF NOT EXISTS dislikes BIGINT DEFAULT 0;
ALTER TABLE files ADD COLUMN IF NOT EXISTS rating NUMERIC(3,1) DEFAULT 0;
ALTER TABLE files ADD COLUMN IF NOT EXISTS review_count BIGINT DEFAULT 0;
ALTER TABLE files ADD COLUMN IF NOT EXISTS free_progress INT DEFAULT 0;
ALTER TABLE files ADD COLUMN IF NOT EXISTS free_unlock_enabled BOOLEAN DEFAULT TRUE;
CREATE INDEX IF NOT EXISTS idx_files_market_server ON files(market_server);
CREATE INDEX IF NOT EXISTS idx_files_owner ON files(owner_id);
CREATE INDEX IF NOT EXISTS idx_files_paid ON files(is_paid);
CREATE INDEX IF NOT EXISTS idx_files_created ON files(created_at DESC);

CREATE TABLE IF NOT EXISTS codes (
    id BIGSERIAL PRIMARY KEY,
    code TEXT UNIQUE NOT NULL,
    owner_id BIGINT,
    buyer_id BIGINT,
    price BIGINT DEFAULT 0,
    is_paid BOOLEAN DEFAULT FALSE,
    total_media INT DEFAULT 0,
    total_size BIGINT DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS medias (
    id BIGSERIAL PRIMARY KEY,
    code TEXT,
    file_id TEXT,
    file_type TEXT,
    file_size BIGINT
);
CREATE INDEX IF NOT EXISTS idx_medias_code ON medias(code);

CREATE TABLE IF NOT EXISTS payments (
    id BIGSERIAL PRIMARY KEY,
    order_id TEXT UNIQUE,
    user_id BIGINT,
    code TEXT,
    amount BIGINT,
    status TEXT DEFAULT 'pending',
    message_id BIGINT,
    group_message_id BIGINT,
    expires_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW(),
    reference TEXT,
    provider TEXT,
    invoice_id TEXT UNIQUE,
    payment_url TEXT,
    type TEXT DEFAULT 'vip',
    paid_at TIMESTAMP,
    fail_reason TEXT,
    seller_paid BOOLEAN DEFAULT FALSE
);
CREATE INDEX IF NOT EXISTS idx_payments_user_status ON payments(user_id,status);

CREATE TABLE IF NOT EXISTS vip_users (
    user_id BIGINT PRIMARY KEY,
    plan TEXT DEFAULT 'vip',
    expired_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS vip_manual_payments (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL,
    package_id TEXT NOT NULL,
    amount BIGINT NOT NULL,
    status TEXT DEFAULT 'pending',
    reason TEXT,
    admin_id BIGINT,
    created_at TIMESTAMP DEFAULT NOW(),
    reviewed_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS file_purchases (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT,
    code TEXT,
    file_code TEXT,
    owner_id BIGINT,
    paid_price BIGINT DEFAULT 0,
    payment_id TEXT,
    status TEXT DEFAULT 'pending',
    qr_string TEXT,
    qr_image TEXT,
    payment_url TEXT,
    expires_at TIMESTAMP,
    qr_message_id BIGINT,
    qr_chat_id BIGINT,
    paid_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_file_purchases_user ON file_purchases(user_id);
CREATE INDEX IF NOT EXISTS idx_file_purchases_status ON file_purchases(status);
CREATE UNIQUE INDEX IF NOT EXISTS uq_file_purchases_payment_id ON file_purchases(payment_id) WHERE payment_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS creator_payments (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL,
    amount BIGINT NOT NULL DEFAULT 150000,
    status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','approved','rejected')),
    admin_id BIGINT,
    reason TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    reviewed_at TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_creator_payments_status ON creator_payments(status);
CREATE INDEX IF NOT EXISTS idx_creator_payments_user ON creator_payments(user_id);

CREATE TABLE IF NOT EXISTS creator_earnings (
    id BIGSERIAL PRIMARY KEY,
    seller_id BIGINT NOT NULL,
    file_code TEXT NOT NULL,
    purchase_id BIGINT,
    gross_amount BIGINT NOT NULL,
    creator_amount BIGINT NOT NULL,
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(purchase_id)
);
CREATE INDEX IF NOT EXISTS idx_creator_earnings_seller ON creator_earnings(seller_id);

CREATE TABLE IF NOT EXISTS transactions (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT,
    amount BIGINT,
    type TEXT,
    status TEXT DEFAULT 'pending',
    description TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_transactions_user ON transactions(user_id);

CREATE TABLE IF NOT EXISTS withdraws (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT,
    amount BIGINT NOT NULL DEFAULT 0,
    method TEXT,
    method_name TEXT,
    account TEXT,
    account_number TEXT,
    account_name TEXT,
    fee BIGINT NOT NULL DEFAULT 0,
    total_cut BIGINT NOT NULL DEFAULT 0,
    receive_amount BIGINT NOT NULL DEFAULT 0,
    status TEXT DEFAULT 'pending',
    channel_message_id BIGINT,
    admin_id BIGINT,
    reason TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    reviewed_at TIMESTAMP
);
ALTER TABLE withdraws ADD COLUMN IF NOT EXISTS method_name TEXT;
ALTER TABLE withdraws ADD COLUMN IF NOT EXISTS account_number TEXT;
ALTER TABLE withdraws ADD COLUMN IF NOT EXISTS account_name TEXT;
ALTER TABLE withdraws ADD COLUMN IF NOT EXISTS fee BIGINT DEFAULT 0;
ALTER TABLE withdraws ADD COLUMN IF NOT EXISTS total_cut BIGINT DEFAULT 0;
ALTER TABLE withdraws ADD COLUMN IF NOT EXISTS receive_amount BIGINT DEFAULT 0;
ALTER TABLE withdraws ADD COLUMN IF NOT EXISTS channel_message_id BIGINT;
ALTER TABLE withdraws ADD COLUMN IF NOT EXISTS admin_id BIGINT;
ALTER TABLE withdraws ADD COLUMN IF NOT EXISTS reason TEXT;
ALTER TABLE withdraws ADD COLUMN IF NOT EXISTS reviewed_at TIMESTAMP;
CREATE INDEX IF NOT EXISTS idx_withdraws_status ON withdraws(status);
CREATE INDEX IF NOT EXISTS idx_withdraws_user ON withdraws(user_id);

CREATE TABLE IF NOT EXISTS user_payment_methods (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL,
    method_name TEXT NOT NULL,
    account_number TEXT NOT NULL,
    account_name TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_user_payment_methods_user ON user_payment_methods(user_id);

CREATE TABLE IF NOT EXISTS file_views (
    user_id BIGINT NOT NULL,
    file_code TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT NOW(),
    PRIMARY KEY(user_id,file_code)
);
CREATE TABLE IF NOT EXISTS file_reactions (
    user_id BIGINT NOT NULL,
    file_code TEXT NOT NULL,
    reaction TEXT NOT NULL CHECK(reaction IN ('like','dislike')),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    PRIMARY KEY(user_id,file_code)
);
CREATE TABLE IF NOT EXISTS file_favorites (
    user_id BIGINT NOT NULL,
    file_code TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT NOW(),
    PRIMARY KEY(user_id,file_code)
);
CREATE TABLE IF NOT EXISTS file_ratings (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL,
    file_code TEXT NOT NULL,
    rating INT NOT NULL CHECK(rating BETWEEN 1 AND 5),
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(user_id,file_code)
);
CREATE TABLE IF NOT EXISTS file_reviews (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL,
    file_code TEXT NOT NULL,
    review TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(user_id,file_code)
);
CREATE INDEX IF NOT EXISTS idx_file_reviews_code ON file_reviews(file_code);
CREATE INDEX IF NOT EXISTS idx_file_ratings_code ON file_ratings(file_code);
CREATE INDEX IF NOT EXISTS idx_file_favorites_code ON file_favorites(file_code);

CREATE TABLE IF NOT EXISTS free_code_progress (
    id BIGSERIAL PRIMARY KEY,
    code TEXT NOT NULL,
    user_id BIGINT NOT NULL,
    purchase_count INT DEFAULT 0,
    completed BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT NOW(),
    completed_at TIMESTAMP,
    UNIQUE(code,user_id)
);
CREATE TABLE IF NOT EXISTS free_code_unlocks (
    id BIGSERIAL PRIMARY KEY,
    code TEXT NOT NULL,
    user_id BIGINT NOT NULL,
    share_count INT DEFAULT 0,
    completed BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT NOW(),
    completed_at TIMESTAMP,
    UNIQUE(code,user_id)
);

CREATE TABLE IF NOT EXISTS logs (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT,
    action TEXT,
    data TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Keep existing balances consistent with the wallet table.
INSERT INTO wallets(user_id,balance)
SELECT user_id, COALESCE(balance,0) FROM users
ON CONFLICT(user_id) DO UPDATE SET balance=EXCLUDED.balance;

-- Marketplace defaults.
UPDATE files SET market_server='1' WHERE market_server IS NULL OR market_server='';
UPDATE files SET views=GREATEST(COALESCE(views,0),COALESCE(view_count,0));
UPDATE files SET sold=GREATEST(COALESCE(sold,0),COALESCE(buy_count,0));

-- Server reference:
-- 1 = General Media
-- 2 = Non-Sexual Teen Media
-- 3 = 18+ Non-Explicit Media
