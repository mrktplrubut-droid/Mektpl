import asyncio
import logging

import asyncpg

from config import DATABASE_URL

_pool = None
_lock = asyncio.Lock()


# ========================
# CONNECTION
# ========================
async def get_pool():
    global _pool

    if _pool is not None:
        return _pool

    async with _lock:
        if _pool is not None:
            return _pool

        while True:
            try:
                logging.info("🔌 Connecting to PostgreSQL...")

                _pool = await asyncpg.create_pool(
                    dsn=DATABASE_URL,
                    min_size=1,
                    max_size=10,
                    command_timeout=60,
                    max_inactive_connection_lifetime=300,
                    statement_cache_size=0,
                    ssl="require",
                )

                # DEBUG DATABASE
                async with _pool.acquire() as conn:
                    db = await conn.fetchval(
                        "SELECT current_database()"
                    )

                    schema = await conn.fetch("""
                        SELECT column_name
                        FROM information_schema.columns
                        WHERE table_name='file_purchases'
                        ORDER BY ordinal_position
                    """)

                    logging.info(f"DATABASE = {db}")
                    logging.info(
                        f"COLUMNS = {[r['column_name'] for r in schema]}"
                    )

                logging.info("✅ PostgreSQL connected")
                break

            except Exception:
                logging.exception(
                    "❌ Failed connecting to PostgreSQL. Retrying in 3 seconds..."
                )
                await asyncio.sleep(3)

    return _pool

# ========================
# CLOSE DATABASE
# ========================
async def close_db():
    global _pool

    if _pool is not None:
        await _pool.close()
        _pool = None
        logging.info("🔌 Database closed")

# ========================
# INIT DATABASE (AUTO FIX)
# ========================
async def init_db():
    pool = await get_pool()

    async with pool.acquire() as conn:

        # ========================
        # USERS
        # ========================
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id BIGINT PRIMARY KEY,
            username TEXT,
            fullname TEXT,
            created_at TIMESTAMP DEFAULT NOW(),
            is_banned BOOLEAN DEFAULT FALSE,
            is_admin BOOLEAN DEFAULT FALSE
        );
        """)

        await conn.execute("""
        ALTER TABLE users
        ADD COLUMN IF NOT EXISTS is_banned BOOLEAN DEFAULT FALSE;
        """)

        await conn.execute("""
        ALTER TABLE users
        ADD COLUMN IF NOT EXISTS is_admin BOOLEAN DEFAULT FALSE;
        """)

        # ========================
        # USER / CREATOR / MEMBERSHIP COMPATIBILITY
        # ========================
        # Keep existing deployments compatible with the bot code.
        user_columns = [
            ("chat_id", "BIGINT"),
            ("full_name", "TEXT"),
            ("fullname", "TEXT"),
            ("last_seen", "TIMESTAMP"),
            ("balance", "BIGINT DEFAULT 0"),
            ("total_earn", "BIGINT DEFAULT 0"),
            ("total_referral", "BIGINT DEFAULT 0"),
            ("referral_count", "BIGINT DEFAULT 0"),
            ("ref_10_claimed", "BOOLEAN DEFAULT FALSE"),
            ("ref_20_claimed", "BOOLEAN DEFAULT FALSE"),
            ("ref_50_claimed", "BOOLEAN DEFAULT FALSE"),
            ("referred_by", "BIGINT"),
            ("is_creator", "BOOLEAN DEFAULT FALSE"),
            ("creator_status", "TEXT DEFAULT 'none'"),
            ("creator_verified_at", "TIMESTAMP"),
            ("phone", "TEXT"),
            ("creator_telegram", "TEXT"),
            ("updated_at", "TIMESTAMP DEFAULT NOW()"),
            ("vip", "BOOLEAN DEFAULT FALSE"),
            ("is_vip", "BOOLEAN DEFAULT FALSE"),
            ("vvip", "BOOLEAN DEFAULT FALSE"),
            ("is_vvip", "BOOLEAN DEFAULT FALSE"),
            ("plan", "TEXT DEFAULT 'free'"),
            ("vip_until", "TIMESTAMP"),
            ("vip_expired", "TIMESTAMP"),
            ("vvip_until", "TIMESTAMP"),
            ("vvip_expired", "TIMESTAMP"),
            ("expired_at", "TIMESTAMP"),
            ("language", "TEXT"),
            ("free_share_count", "INT DEFAULT 0"),
            ("paid_quota", "INT DEFAULT 0")
        ]

        for column_name, column_type in user_columns:
            await conn.execute(
                f"ALTER TABLE users ADD COLUMN IF NOT EXISTS {column_name} {column_type};"
            )

        # Synchronize the two common Telegram/name aliases when both exist.
        await conn.execute("""
            UPDATE users
            SET chat_id = user_id
            WHERE chat_id IS NULL;
        """)

        await conn.execute("""
            UPDATE users
            SET full_name = COALESCE(full_name, fullname)
            WHERE full_name IS NULL AND fullname IS NOT NULL;
        """)

        await conn.execute("""
            UPDATE users
            SET fullname = COALESCE(fullname, full_name)
            WHERE fullname IS NULL AND full_name IS NOT NULL;
        """)

        # ========================
        # SETTINGS
        # ========================
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        );
        """)

        await conn.execute("""
        INSERT INTO settings (key, value)
        VALUES ('maintenance', 'off')
        ON CONFLICT (key) DO NOTHING;
        """)

        # ========================
        # WALLETS
        # ========================
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS wallets (
            user_id BIGINT PRIMARY KEY,
            balance BIGINT DEFAULT 0
        );
        """)

        # ========================
        # CODES
        # ========================
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS codes (
            id SERIAL PRIMARY KEY,
            code TEXT UNIQUE NOT NULL,
            owner_id BIGINT,
            buyer_id BIGINT,
            price BIGINT DEFAULT 0,
            is_paid BOOLEAN DEFAULT FALSE,
            total_media INT DEFAULT 0,
            total_size BIGINT DEFAULT 0,
            created_at TIMESTAMP DEFAULT NOW()
        );
        """)

        # ========================
        # MEDIAS
        # ========================
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS medias (
            id SERIAL PRIMARY KEY,
            code TEXT,
            file_id TEXT,
            file_type TEXT,
            file_size BIGINT
        );
        """)

        # ========================
        # PAYMENTS
        # ========================
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS payments (
            id SERIAL PRIMARY KEY,
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
            fail_reason TEXT
        );
        """)

        # Keep payment schema compatible with the VIP automatic flow.
        for column_name, column_type in [
            ("reference", "TEXT"),
            ("provider", "TEXT"),
            ("invoice_id", "TEXT"),
            ("payment_url", "TEXT"),
            ("type", "TEXT DEFAULT 'vip'"),
            ("paid_at", "TIMESTAMP"),
            ("fail_reason", "TEXT"),
            ("seller_paid", "BOOLEAN DEFAULT FALSE"),
        ]:
            await conn.execute(
                f"ALTER TABLE payments ADD COLUMN IF NOT EXISTS {column_name} {column_type};"
            )

        await conn.execute("""
        CREATE TABLE IF NOT EXISTS vip_manual_payments (
            id SERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL,
            package_id TEXT NOT NULL,
            amount BIGINT NOT NULL,
            status TEXT DEFAULT 'pending',
            reason TEXT,
            admin_id BIGINT,
            created_at TIMESTAMP DEFAULT NOW(),
            reviewed_at TIMESTAMP
        );
        """)

        await conn.execute("""
        CREATE TABLE IF NOT EXISTS free_code_progress (
            id BIGSERIAL PRIMARY KEY,
            code TEXT NOT NULL,
            user_id BIGINT NOT NULL,
            purchase_count INT DEFAULT 0,
            completed BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMP DEFAULT NOW(),
            completed_at TIMESTAMP,
            UNIQUE(code, user_id)
        );
        """)

        await conn.execute("""
        CREATE TABLE IF NOT EXISTS file_reviews (
            id BIGSERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL,
            file_code TEXT NOT NULL,
            review TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW(),
            UNIQUE(user_id, file_code)
        );
        """)

        await conn.execute("""
        CREATE TABLE IF NOT EXISTS free_code_unlocks (
            id SERIAL PRIMARY KEY,
            code TEXT NOT NULL,
            user_id BIGINT NOT NULL,
            share_count INT DEFAULT 0,
            completed BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMP DEFAULT NOW(),
            completed_at TIMESTAMP,
            UNIQUE(code, user_id)
        );
        """)

        # ========================
        # TRANSACTIONS
        # ========================
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            id SERIAL PRIMARY KEY,
            user_id BIGINT,
            amount BIGINT,
            type TEXT,
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT NOW()
        );
        """)

        # ========================
        # WITHDRAW
        # ========================
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS withdraws (
            id SERIAL PRIMARY KEY,
            user_id BIGINT,
            amount BIGINT,
            method TEXT,
            account TEXT,
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT NOW()
        );
        """)

        # ========================
        # FILE PURCHASES
        # ========================
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS file_purchases (
            id SERIAL PRIMARY KEY,
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
        """)

        # ========================
        # AUTO FIX FILE_PURCHASES
        # ========================

        await conn.execute("""
        ALTER TABLE file_purchases
        ADD COLUMN IF NOT EXISTS user_id BIGINT;
        """)

        await conn.execute("""
        ALTER TABLE file_purchases
        ADD COLUMN IF NOT EXISTS code TEXT;
        """)

        await conn.execute("""
        ALTER TABLE file_purchases
        ADD COLUMN IF NOT EXISTS file_code TEXT;
        """)

        await conn.execute("""
        ALTER TABLE file_purchases
        ADD COLUMN IF NOT EXISTS owner_id BIGINT;
        """)

        await conn.execute("""
        ALTER TABLE file_purchases
        ADD COLUMN IF NOT EXISTS paid_price BIGINT DEFAULT 0;
        """)

        await conn.execute("""
        ALTER TABLE file_purchases
        ADD COLUMN IF NOT EXISTS payment_id TEXT;
        """)

        await conn.execute("""
        ALTER TABLE file_purchases
        ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'pending';
        """)

        await conn.execute("""
        ALTER TABLE file_purchases
        ADD COLUMN IF NOT EXISTS qr_string TEXT;
        """)

        await conn.execute("""
        ALTER TABLE file_purchases
        ADD COLUMN IF NOT EXISTS qr_image TEXT;
        """)

        await conn.execute("""
        ALTER TABLE file_purchases
        ADD COLUMN IF NOT EXISTS payment_url TEXT;
        """)

        await conn.execute("""
        ALTER TABLE file_purchases
        ADD COLUMN IF NOT EXISTS expires_at TIMESTAMP;
        """)

        await conn.execute("""
        ALTER TABLE file_purchases
        ADD COLUMN IF NOT EXISTS qr_message_id BIGINT;
        """)

        await conn.execute("""
        ALTER TABLE file_purchases
        ADD COLUMN IF NOT EXISTS qr_chat_id BIGINT;
        """)

        await conn.execute("""
        ALTER TABLE file_purchases
        ADD COLUMN IF NOT EXISTS paid_at TIMESTAMP;
        """)

        # ========================
        # MARKETPLACE REAL-TIME COUNTERS / REACTIONS
        # ========================
        file_columns = [
            ("views", "BIGINT DEFAULT 0"),
            ("view_count", "BIGINT DEFAULT 0"),
            ("sold", "BIGINT DEFAULT 0"),
            ("buy_count", "BIGINT DEFAULT 0"),
            ("favorite_count", "BIGINT DEFAULT 0"),
            ("likes", "BIGINT DEFAULT 0"),
            ("dislikes", "BIGINT DEFAULT 0"),
            ("rating", "NUMERIC(3,1) DEFAULT 0"),
            ("review_count", "BIGINT DEFAULT 0"),
            ("seller_id", "BIGINT"),
            ("owner_id", "BIGINT"),
            ("free_progress", "INT DEFAULT 0"),
            ("free_unlock_enabled", "BOOLEAN DEFAULT TRUE"),
        ]

        for column_name, column_type in file_columns:
            await conn.execute(
                f"ALTER TABLE files ADD COLUMN IF NOT EXISTS {column_name} {column_type};"
            )

        await conn.execute("""
            UPDATE files
            SET views = GREATEST(COALESCE(views, 0), COALESCE(view_count, 0)),
                sold = GREATEST(COALESCE(sold, 0), COALESCE(buy_count, 0))
        """)

        await conn.execute("""
        CREATE TABLE IF NOT EXISTS file_views (
            user_id BIGINT NOT NULL,
            file_code TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT NOW(),
            PRIMARY KEY (user_id, file_code)
        );
        """)

        await conn.execute("""
        CREATE TABLE IF NOT EXISTS file_reactions (
            user_id BIGINT NOT NULL,
            file_code TEXT NOT NULL,
            reaction TEXT NOT NULL CHECK (reaction IN ('like','dislike')),
            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW(),
            PRIMARY KEY (user_id, file_code)
        );
        """)

        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_file_views_code
            ON file_views(file_code);
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_file_reactions_code
            ON file_reactions(file_code);
        """)

        # Repair old referral counters: referral_count is the canonical counter.
        await conn.execute("""
            UPDATE users
            SET referral_count = GREATEST(
                COALESCE(referral_count, 0),
                COALESCE(total_referral, 0)
            );
        """)

        # ========================
        # LOGS
        # ========================
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS logs (
            id SERIAL PRIMARY KEY,
            user_id BIGINT,
            action TEXT,
            data TEXT,
            created_at TIMESTAMP DEFAULT NOW()
        );
        """)

        # ========================
        # DEBUG FILE_PURCHASES
        # ========================
        columns = await conn.fetch("""
            SELECT column_name, data_type
            FROM information_schema.columns
            WHERE table_name = 'file_purchases'
            ORDER BY ordinal_position;
        """)

        logging.info(
            "📦 FILE_PURCHASES COLUMNS = %s",
            [
                f"{row['column_name']} ({row['data_type']})"
                for row in columns
            ]
        )

        print("✅ Database initialized")


# ========================
# QUERY HELPERS
# ========================
async def execute(query, *args, retry=1):
    for attempt in range(retry + 1):
        try:
            pool = await get_pool()

            async with pool.acquire() as conn:
                return await conn.execute(query, *args)

        except Exception:
            logging.exception("EXECUTE ERROR")

            if attempt >= retry:
                raise

            await asyncio.sleep(1)


async def fetch(query, *args, retry=1):
    for attempt in range(retry + 1):
        try:
            pool = await get_pool()

            async with pool.acquire() as conn:
                return await conn.fetch(query, *args)

        except Exception:
            logging.exception("FETCH ERROR")

            if attempt >= retry:
                raise

            await asyncio.sleep(1)


async def fetchrow(query, *args, retry=1):
    for attempt in range(retry + 1):
        try:
            pool = await get_pool()

            async with pool.acquire() as conn:
                return await conn.fetchrow(query, *args)

        except Exception:
            logging.exception("FETCHROW ERROR")

            if attempt >= retry:
                raise

            await asyncio.sleep(1)


async def fetchval(query, *args, retry=1):
    for attempt in range(retry + 1):
        try:
            pool = await get_pool()

            async with pool.acquire() as conn:
                return await conn.fetchval(query, *args)

        except Exception:
            logging.exception("FETCHVAL ERROR")

            if attempt >= retry:
                raise

            await asyncio.sleep(1)


# ========================
# TRANSACTION
# ========================
async def transaction(queries: list):
    pool = await get_pool()

    async with pool.acquire() as conn:
        async with conn.transaction():
            results = []

            for q in queries:
                query = q[0]
                args = q[1:]

                results.append(
                    await conn.execute(query, *args)
                )

            return results
