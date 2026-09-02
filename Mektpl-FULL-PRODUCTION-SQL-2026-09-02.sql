-- ============================================================
-- MEKTPL / MARKET BOT - FULL PRODUCTION DATABASE
-- Safe/idempotent migration for an existing PostgreSQL database.
-- Run in Supabase/PostgreSQL SQL Editor.
-- IMPORTANT: never put BOT_TOKEN, DB password, API keys, or secrets here.
-- ============================================================

BEGIN;

CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- -------------------------
-- USERS / ACCOUNT
-- -------------------------
CREATE TABLE IF NOT EXISTS users (
    user_id BIGINT PRIMARY KEY,
    chat_id BIGINT,
    username TEXT,
    fullname TEXT,
    full_name TEXT,
    language TEXT DEFAULT 'id' CHECK (language IN ('id','en')),
    balance BIGINT NOT NULL DEFAULT 0 CHECK (balance >= 0),
    total_earn BIGINT NOT NULL DEFAULT 0,
    total_referral BIGINT NOT NULL DEFAULT 0,
    referral_count BIGINT NOT NULL DEFAULT 0,
    referred_by BIGINT,
    ref_10_claimed BOOLEAN NOT NULL DEFAULT FALSE,
    ref_20_claimed BOOLEAN NOT NULL DEFAULT FALSE,
    ref_50_claimed BOOLEAN NOT NULL DEFAULT FALSE,
    is_creator BOOLEAN NOT NULL DEFAULT FALSE,
    creator_status TEXT NOT NULL DEFAULT 'none',
    creator_verified_at TIMESTAMP,
    creator_telegram TEXT,
    phone TEXT,
    is_banned BOOLEAN NOT NULL DEFAULT FALSE,
    is_admin BOOLEAN NOT NULL DEFAULT FALSE,
    vip BOOLEAN NOT NULL DEFAULT FALSE,
    is_vip BOOLEAN NOT NULL DEFAULT FALSE,
    vvip BOOLEAN NOT NULL DEFAULT FALSE,
    is_vvip BOOLEAN NOT NULL DEFAULT FALSE,
    plan TEXT NOT NULL DEFAULT 'free',
    vip_until TIMESTAMP,
    vip_expired TIMESTAMP,
    vvip_until TIMESTAMP,
    vvip_expired TIMESTAMP,
    expired_at TIMESTAMP,
    free_share_count INT NOT NULL DEFAULT 0,
    paid_quota INT NOT NULL DEFAULT 0,
    total_withdraw BIGINT NOT NULL DEFAULT 0,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    last_seen TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

ALTER TABLE users ADD COLUMN IF NOT EXISTS chat_id BIGINT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS username TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS fullname TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS full_name TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS language TEXT DEFAULT 'id';
ALTER TABLE users ADD COLUMN IF NOT EXISTS balance BIGINT DEFAULT 0;
ALTER TABLE users ADD COLUMN IF NOT EXISTS total_earn BIGINT DEFAULT 0;
ALTER TABLE users ADD COLUMN IF NOT EXISTS total_referral BIGINT DEFAULT 0;
ALTER TABLE users ADD COLUMN IF NOT EXISTS referral_count BIGINT DEFAULT 0;
ALTER TABLE users ADD COLUMN IF NOT EXISTS referred_by BIGINT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS ref_10_claimed BOOLEAN DEFAULT FALSE;
ALTER TABLE users ADD COLUMN IF NOT EXISTS ref_20_claimed BOOLEAN DEFAULT FALSE;
ALTER TABLE users ADD COLUMN IF NOT EXISTS ref_50_claimed BOOLEAN DEFAULT FALSE;
ALTER TABLE users ADD COLUMN IF NOT EXISTS is_creator BOOLEAN DEFAULT FALSE;
ALTER TABLE users ADD COLUMN IF NOT EXISTS creator_status TEXT DEFAULT 'none';
ALTER TABLE users ADD COLUMN IF NOT EXISTS creator_verified_at TIMESTAMP;
ALTER TABLE users ADD COLUMN IF NOT EXISTS creator_telegram TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS phone TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS is_banned BOOLEAN DEFAULT FALSE;
ALTER TABLE users ADD COLUMN IF NOT EXISTS is_admin BOOLEAN DEFAULT FALSE;
ALTER TABLE users ADD COLUMN IF NOT EXISTS vip BOOLEAN DEFAULT FALSE;
ALTER TABLE users ADD COLUMN IF NOT EXISTS is_vip BOOLEAN DEFAULT FALSE;
ALTER TABLE users ADD COLUMN IF NOT EXISTS vvip BOOLEAN DEFAULT FALSE;
ALTER TABLE users ADD COLUMN IF NOT EXISTS is_vvip BOOLEAN DEFAULT FALSE;
ALTER TABLE users ADD COLUMN IF NOT EXISTS plan TEXT DEFAULT 'free';
ALTER TABLE users ADD COLUMN IF NOT EXISTS vip_until TIMESTAMP;
ALTER TABLE users ADD COLUMN IF NOT EXISTS vip_expired TIMESTAMP;
ALTER TABLE users ADD COLUMN IF NOT EXISTS vvip_until TIMESTAMP;
ALTER TABLE users ADD COLUMN IF NOT EXISTS vvip_expired TIMESTAMP;
ALTER TABLE users ADD COLUMN IF NOT EXISTS expired_at TIMESTAMP;
ALTER TABLE users ADD COLUMN IF NOT EXISTS free_share_count INT DEFAULT 0;
ALTER TABLE users ADD COLUMN IF NOT EXISTS paid_quota INT DEFAULT 0;
ALTER TABLE users ADD COLUMN IF NOT EXISTS total_withdraw BIGINT DEFAULT 0;
ALTER TABLE users ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT NOW();
ALTER TABLE users ADD COLUMN IF NOT EXISTS last_seen TIMESTAMP;
ALTER TABLE users ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT NOW();

UPDATE users SET chat_id = user_id WHERE chat_id IS NULL;
UPDATE users SET full_name = COALESCE(full_name, fullname) WHERE full_name IS NULL;
UPDATE users SET fullname = COALESCE(fullname, full_name) WHERE fullname IS NULL;
UPDATE users SET language = 'id' WHERE language IS NULL OR language NOT IN ('id','en');
UPDATE users SET balance = 0 WHERE balance IS NULL OR balance < 0;

CREATE INDEX IF NOT EXISTS idx_users_creator ON users(is_creator, creator_status);
CREATE INDEX IF NOT EXISTS idx_users_referrer ON users(referred_by);
CREATE INDEX IF NOT EXISTS idx_users_last_seen ON users(last_seen DESC);

-- -------------------------
-- SETTINGS / ADMIN
-- -------------------------
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);
INSERT INTO settings(key,value) VALUES
('maintenance','off'),
('maintenance_text','Maintenance sedang berlangsung. Silakan coba lagi nanti.'),
('withdraw_enabled','on')
ON CONFLICT(key) DO NOTHING;

CREATE TABLE IF NOT EXISTS admins (
    user_id BIGINT PRIMARY KEY,
    role TEXT NOT NULL DEFAULT 'admin',
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

-- -------------------------
-- FILES / MEDIA / MARKETPLACE
-- -------------------------
CREATE TABLE IF NOT EXISTS files (
    id BIGSERIAL PRIMARY KEY,
    code TEXT UNIQUE NOT NULL,
    title TEXT,
    description TEXT,
    category TEXT,
    creator TEXT,
    media TEXT,
    share_media BOOLEAN DEFAULT FALSE,
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
    views BIGINT DEFAULT 0,
    sold BIGINT DEFAULT 0,
    buy_count BIGINT DEFAULT 0,
    likes BIGINT DEFAULT 0,
    dislikes BIGINT DEFAULT 0,
    rating NUMERIC(3,1) DEFAULT 0,
    review_count BIGINT DEFAULT 0,
    free_progress INT DEFAULT 0,
    free_unlock_enabled BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW()
);

ALTER TABLE files ADD COLUMN IF NOT EXISTS title TEXT;
ALTER TABLE files ADD COLUMN IF NOT EXISTS description TEXT;
ALTER TABLE files ADD COLUMN IF NOT EXISTS category TEXT;
ALTER TABLE files ADD COLUMN IF NOT EXISTS creator TEXT;
ALTER TABLE files ADD COLUMN IF NOT EXISTS media TEXT;
ALTER TABLE files ADD COLUMN IF NOT EXISTS share_media BOOLEAN DEFAULT FALSE;
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
ALTER TABLE files ADD COLUMN IF NOT EXISTS views BIGINT DEFAULT 0;
ALTER TABLE files ADD COLUMN IF NOT EXISTS sold BIGINT DEFAULT 0;
ALTER TABLE files ADD COLUMN IF NOT EXISTS buy_count BIGINT DEFAULT 0;
ALTER TABLE files ADD COLUMN IF NOT EXISTS likes BIGINT DEFAULT 0;
ALTER TABLE files ADD COLUMN IF NOT EXISTS dislikes BIGINT DEFAULT 0;
ALTER TABLE files ADD COLUMN IF NOT EXISTS rating NUMERIC(3,1) DEFAULT 0;
ALTER TABLE files ADD COLUMN IF NOT EXISTS review_count BIGINT DEFAULT 0;
ALTER TABLE files ADD COLUMN IF NOT EXISTS free_progress INT DEFAULT 0;
ALTER TABLE files ADD COLUMN IF NOT EXISTS free_unlock_enabled BOOLEAN DEFAULT TRUE;
ALTER TABLE files ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT NOW();

CREATE INDEX IF NOT EXISTS idx_files_owner ON files(owner_id);
CREATE INDEX IF NOT EXISTS idx_files_seller ON files(seller_id);
CREATE INDEX IF NOT EXISTS idx_files_category ON files(category);
CREATE INDEX IF NOT EXISTS idx_files_created ON files(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_files_paid ON files(is_paid);

CREATE TABLE IF NOT EXISTS medias (
    id BIGSERIAL PRIMARY KEY,
    code TEXT NOT NULL,
    message_id BIGINT,
    file_id TEXT,
    file_type TEXT,
    file_size BIGINT DEFAULT 0,
    title TEXT,
    position INT DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW()
);
ALTER TABLE medias ADD COLUMN IF NOT EXISTS code TEXT;
ALTER TABLE medias ADD COLUMN IF NOT EXISTS message_id BIGINT;
ALTER TABLE medias ADD COLUMN IF NOT EXISTS file_id TEXT;
ALTER TABLE medias ADD COLUMN IF NOT EXISTS file_type TEXT;
ALTER TABLE medias ADD COLUMN IF NOT EXISTS file_size BIGINT DEFAULT 0;
ALTER TABLE medias ADD COLUMN IF NOT EXISTS title TEXT;
ALTER TABLE medias ADD COLUMN IF NOT EXISTS position INT DEFAULT 0;
ALTER TABLE medias ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT NOW();
CREATE INDEX IF NOT EXISTS idx_medias_code ON medias(code);
CREATE INDEX IF NOT EXISTS idx_medias_message ON medias(message_id);

-- -------------------------
-- PURCHASES / PAYMENTS
-- -------------------------
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
    expires_at TIMESTAMP WITH TIME ZONE,
    qr_message_id BIGINT,
    qr_chat_id BIGINT,
    paid_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW()
);
ALTER TABLE file_purchases ADD COLUMN IF NOT EXISTS user_id BIGINT;
ALTER TABLE file_purchases ADD COLUMN IF NOT EXISTS code TEXT;
ALTER TABLE file_purchases ADD COLUMN IF NOT EXISTS file_code TEXT;
ALTER TABLE file_purchases ADD COLUMN IF NOT EXISTS owner_id BIGINT;
ALTER TABLE file_purchases ADD COLUMN IF NOT EXISTS paid_price BIGINT DEFAULT 0;
ALTER TABLE file_purchases ADD COLUMN IF NOT EXISTS payment_id TEXT;
ALTER TABLE file_purchases ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'pending';
ALTER TABLE file_purchases ADD COLUMN IF NOT EXISTS qr_string TEXT;
ALTER TABLE file_purchases ADD COLUMN IF NOT EXISTS qr_image TEXT;
ALTER TABLE file_purchases ADD COLUMN IF NOT EXISTS payment_url TEXT;
ALTER TABLE file_purchases ADD COLUMN IF NOT EXISTS expires_at TIMESTAMP WITH TIME ZONE;
ALTER TABLE file_purchases ADD COLUMN IF NOT EXISTS qr_message_id BIGINT;
ALTER TABLE file_purchases ADD COLUMN IF NOT EXISTS qr_chat_id BIGINT;
ALTER TABLE file_purchases ADD COLUMN IF NOT EXISTS paid_at TIMESTAMP;
ALTER TABLE file_purchases ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT NOW();
ALTER TABLE file_purchases ADD COLUMN IF NOT EXISTS media_session_id TEXT;
CREATE INDEX IF NOT EXISTS idx_file_purchases_user ON file_purchases(user_id);
CREATE INDEX IF NOT EXISTS idx_file_purchases_code ON file_purchases(file_code);
CREATE INDEX IF NOT EXISTS idx_file_purchases_status ON file_purchases(status);

CREATE TABLE IF NOT EXISTS payments (
    id BIGSERIAL PRIMARY KEY,
    order_id TEXT UNIQUE,
    user_id BIGINT,
    code TEXT,
    amount BIGINT NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'pending',
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
ALTER TABLE payments ADD COLUMN IF NOT EXISTS order_id TEXT;
ALTER TABLE payments ADD COLUMN IF NOT EXISTS user_id BIGINT;
ALTER TABLE payments ADD COLUMN IF NOT EXISTS code TEXT;
ALTER TABLE payments ADD COLUMN IF NOT EXISTS amount BIGINT DEFAULT 0;
ALTER TABLE payments ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'pending';
ALTER TABLE payments ADD COLUMN IF NOT EXISTS message_id BIGINT;
ALTER TABLE payments ADD COLUMN IF NOT EXISTS group_message_id BIGINT;
ALTER TABLE payments ADD COLUMN IF NOT EXISTS expires_at TIMESTAMP;
ALTER TABLE payments ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT NOW();
ALTER TABLE payments ADD COLUMN IF NOT EXISTS reference TEXT;
ALTER TABLE payments ADD COLUMN IF NOT EXISTS provider TEXT;
ALTER TABLE payments ADD COLUMN IF NOT EXISTS invoice_id TEXT;
ALTER TABLE payments ADD COLUMN IF NOT EXISTS payment_url TEXT;
ALTER TABLE payments ADD COLUMN IF NOT EXISTS type TEXT DEFAULT 'vip';
ALTER TABLE payments ADD COLUMN IF NOT EXISTS paid_at TIMESTAMP;
ALTER TABLE payments ADD COLUMN IF NOT EXISTS fail_reason TEXT;
ALTER TABLE payments ADD COLUMN IF NOT EXISTS seller_paid BOOLEAN DEFAULT FALSE;
CREATE INDEX IF NOT EXISTS idx_payments_user_status ON payments(user_id,status);
CREATE INDEX IF NOT EXISTS idx_payments_invoice ON payments(invoice_id);

CREATE TABLE IF NOT EXISTS transactions (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT,
    amount BIGINT DEFAULT 0,
    type TEXT,
    status TEXT DEFAULT 'pending',
    reference TEXT,
    description TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);
ALTER TABLE transactions ADD COLUMN IF NOT EXISTS reference TEXT;
ALTER TABLE transactions ADD COLUMN IF NOT EXISTS description TEXT;
CREATE INDEX IF NOT EXISTS idx_transactions_user ON transactions(user_id,created_at DESC);

-- -------------------------
-- VIP
-- -------------------------
CREATE TABLE IF NOT EXISTS vip_users (
    user_id BIGINT PRIMARY KEY,
    plan TEXT NOT NULL DEFAULT 'FREE',
    expired_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS vip_manual_payments (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL,
    package_id TEXT NOT NULL,
    amount BIGINT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    reason TEXT,
    admin_id BIGINT,
    created_at TIMESTAMP DEFAULT NOW(),
    reviewed_at TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_vip_manual_user_status ON vip_manual_payments(user_id,status);

-- -------------------------
-- CREATOR / FREE ACCESS
-- -------------------------
CREATE TABLE IF NOT EXISTS free_code_progress (
    id BIGSERIAL PRIMARY KEY,
    code TEXT NOT NULL,
    user_id BIGINT NOT NULL,
    purchase_count INT NOT NULL DEFAULT 0,
    completed BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT NOW(),
    completed_at TIMESTAMP,
    UNIQUE(code,user_id)
);
CREATE TABLE IF NOT EXISTS free_code_unlocks (
    id BIGSERIAL PRIMARY KEY,
    code TEXT NOT NULL,
    user_id BIGINT NOT NULL,
    share_count INT NOT NULL DEFAULT 0,
    completed BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT NOW(),
    completed_at TIMESTAMP,
    UNIQUE(code,user_id)
);

-- -------------------------
-- REVIEWS / RATINGS / FAVORITES / REACTIONS / VIEWS
-- -------------------------
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
    updated_at TIMESTAMP DEFAULT NOW(),
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
CREATE INDEX IF NOT EXISTS idx_file_views_code ON file_views(file_code);
CREATE INDEX IF NOT EXISTS idx_file_reactions_code ON file_reactions(file_code);
CREATE INDEX IF NOT EXISTS idx_file_favorites_code ON file_favorites(file_code);
CREATE INDEX IF NOT EXISTS idx_file_ratings_code ON file_ratings(file_code);
CREATE INDEX IF NOT EXISTS idx_file_reviews_code ON file_reviews(file_code);

-- -------------------------
-- WITHDRAW / E-WALLET
-- -------------------------
CREATE TABLE IF NOT EXISTS user_payment_methods (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL,
    method_name TEXT NOT NULL,
    account_number TEXT NOT NULL,
    account_name TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(user_id,method_name,account_number)
);
CREATE INDEX IF NOT EXISTS idx_user_payment_methods_user ON user_payment_methods(user_id);

CREATE TABLE IF NOT EXISTS withdraws (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL,
    method_name TEXT,
    account_number TEXT,
    account_name TEXT,
    method TEXT,
    account TEXT,
    amount BIGINT NOT NULL DEFAULT 0,
    fee BIGINT NOT NULL DEFAULT 0,
    receive_amount BIGINT NOT NULL DEFAULT 0,
    total_cut BIGINT NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TIMESTAMP DEFAULT NOW(),
    processed_at TIMESTAMP,
    paid_at TIMESTAMP,
    admin_note TEXT,
    transaction_id TEXT
);
ALTER TABLE withdraws ADD COLUMN IF NOT EXISTS method_name TEXT;
ALTER TABLE withdraws ADD COLUMN IF NOT EXISTS account_number TEXT;
ALTER TABLE withdraws ADD COLUMN IF NOT EXISTS account_name TEXT;
ALTER TABLE withdraws ADD COLUMN IF NOT EXISTS method TEXT;
ALTER TABLE withdraws ADD COLUMN IF NOT EXISTS account TEXT;
ALTER TABLE withdraws ADD COLUMN IF NOT EXISTS amount BIGINT DEFAULT 0;
ALTER TABLE withdraws ADD COLUMN IF NOT EXISTS fee BIGINT DEFAULT 0;
ALTER TABLE withdraws ADD COLUMN IF NOT EXISTS receive_amount BIGINT DEFAULT 0;
ALTER TABLE withdraws ADD COLUMN IF NOT EXISTS total_cut BIGINT DEFAULT 0;
ALTER TABLE withdraws ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'pending';
ALTER TABLE withdraws ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT NOW();
ALTER TABLE withdraws ADD COLUMN IF NOT EXISTS processed_at TIMESTAMP;
ALTER TABLE withdraws ADD COLUMN IF NOT EXISTS paid_at TIMESTAMP;
ALTER TABLE withdraws ADD COLUMN IF NOT EXISTS admin_note TEXT;
ALTER TABLE withdraws ADD COLUMN IF NOT EXISTS transaction_id TEXT;
ALTER TABLE withdraws ADD COLUMN IF NOT EXISTS channel_message_id BIGINT;
ALTER TABLE withdraws ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT NOW();

UPDATE withdraws
SET receive_amount = COALESCE(receive_amount, amount, 0)
WHERE receive_amount IS NULL;
UPDATE withdraws
SET total_cut = COALESCE(total_cut,0)
WHERE total_cut IS NULL OR total_cut = 0;
UPDATE withdraws
SET total_cut = COALESCE(amount,0) + COALESCE(fee,0)
WHERE total_cut = 0;
UPDATE withdraws
SET receive_amount = COALESCE(amount,0)
WHERE receive_amount = 0 AND COALESCE(amount,0) > 0;

ALTER TABLE withdraws ALTER COLUMN receive_amount SET DEFAULT 0;
ALTER TABLE withdraws ALTER COLUMN receive_amount SET NOT NULL;
ALTER TABLE withdraws ALTER COLUMN total_cut SET DEFAULT 0;
ALTER TABLE withdraws ALTER COLUMN total_cut SET NOT NULL;
CREATE INDEX IF NOT EXISTS idx_withdraws_user ON withdraws(user_id,created_at DESC);
CREATE INDEX IF NOT EXISTS idx_withdraws_status ON withdraws(status,created_at DESC);

CREATE TABLE IF NOT EXISTS wallets (
    user_id BIGINT PRIMARY KEY,
    balance BIGINT NOT NULL DEFAULT 0 CHECK(balance >= 0)
);

-- -------------------------
-- LOGS
-- -------------------------
CREATE TABLE IF NOT EXISTS logs (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT,
    action TEXT,
    data TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_logs_created ON logs(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_logs_user ON logs(user_id,created_at DESC);

-- -------------------------
-- DATA REPAIR / COUNTER SYNC
-- -------------------------
UPDATE files f
SET
    views = GREATEST(COALESCE(f.views,0),COALESCE(f.view_count,0)),
    sold = GREATEST(COALESCE(f.sold,0),COALESCE(f.buy_count,0)),
    favorite_count = (SELECT COUNT(*) FROM file_favorites x WHERE x.file_code=f.code),
    likes = (SELECT COUNT(*) FROM file_reactions x WHERE x.file_code=f.code AND x.reaction='like'),
    dislikes = (SELECT COUNT(*) FROM file_reactions x WHERE x.file_code=f.code AND x.reaction='dislike'),
    rating = COALESCE((SELECT ROUND(AVG(x.rating)::numeric,1) FROM file_ratings x WHERE x.file_code=f.code),0),
    review_count = (SELECT COUNT(*) FROM file_ratings x WHERE x.file_code=f.code)
WHERE TRUE;

COMMIT;

-- ============================================================
-- OPTIONAL: set these through the bot's environment variables,
-- not by storing Telegram secrets in this SQL file.
-- ============================================================
-- BOT_USERNAME=mktplbot
-- REVIEW_CHANNEL_URL=https://t.me/...
-- NOTIFICATION_CHANNEL_URL=https://t.me/...
-- TRANSACTION_CHANNEL_URL=https://t.me/...
-- ALL_CODE_CHANNEL_URL=https://t.me/...
