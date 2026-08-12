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
        # USERS
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

        # FIX kalau tabel lama belum ada kolom
        await conn.execute("""
        ALTER TABLE users ADD COLUMN IF NOT EXISTS is_banned BOOLEAN DEFAULT FALSE;
        """)
        await conn.execute("""
        ALTER TABLE users ADD COLUMN IF NOT EXISTS is_admin BOOLEAN DEFAULT FALSE;
        """)

        # SETTINGS
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

        # WALLETS
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS wallets (
            user_id BIGINT PRIMARY KEY,
            balance BIGINT DEFAULT 0
        );
        """)

        # CODES
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

        # MEDIAS
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS medias (
            id SERIAL PRIMARY KEY,
            code TEXT,
            file_id TEXT,
            file_type TEXT,
            file_size BIGINT
        );
        """)

        # PAYMENTS
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
            created_at TIMESTAMP DEFAULT NOW()
        );
        """)

        # TRANSACTIONS
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

        # WITHDRAW
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

        # FILE PURCHASE
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS file_purchases (
            id SERIAL PRIMARY KEY,
            user_id BIGINT,
            code TEXT,
            created_at TIMESTAMP DEFAULT NOW(),
            UNIQUE(user_id, code)
        );
        """)

        # LOGS
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS logs (
            id SERIAL PRIMARY KEY,
            user_id BIGINT,
            action TEXT,
            data TEXT,
            created_at TIMESTAMP DEFAULT NOW()
        );
        """)

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
