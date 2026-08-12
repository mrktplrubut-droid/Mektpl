import logging
import os
import json

import redis.asyncio as redis

logger = logging.getLogger(__name__)

# =========================
# CONFIG
# =========================
REDIS_URL = os.getenv("REDIS_URL")

redis_client = None


# =========================
# INIT (WAJIB DIPANGGIL)
# =========================
async def init_redis():
    global redis_client

    if not REDIS_URL:
        logger.warning("⚠️ REDIS_URL not found, Redis disabled")
        return None

    try:
        redis_client = redis.from_url(
            REDIS_URL,
            decode_responses=True,
            socket_connect_timeout=5,
            socket_timeout=5,
            retry_on_timeout=True,
            health_check_interval=30,
        )

        # 🔥 TEST KONEKSI
        await redis_client.ping()

        logger.info("✅ Redis connected")

    except Exception:
        logger.exception("❌ Failed to connect Redis")
        redis_client = None

    return redis_client


# =========================
# SAFE SET
# =========================
async def safe_set(
    key: str,
    value,
    ex: int | None = None,
    nx: bool = False,
):
    if redis_client is None:
        return False

    try:
        # 🔥 AUTO JSON
        if isinstance(value, (dict, list)):
            value = json.dumps(value)

        return await redis_client.set(
            key,
            value,
            ex=ex,
            nx=nx,
        )

    except Exception:
        logger.exception("Redis SET failed")
        return False


# =========================
# SAFE GET
# =========================
async def safe_get(key: str):
    if redis_client is None:
        return None

    try:
        value = await redis_client.get(key)

        if value is None:
            return None

        # 🔥 AUTO PARSE JSON
        try:
            return json.loads(value)
        except:
            return value

    except Exception:
        logger.exception("Redis GET failed")
        return None


# =========================
# DELETE
# =========================
async def safe_delete(key: str):
    if redis_client is None:
        return False

    try:
        return await redis_client.delete(key)

    except Exception:
        logger.exception("Redis DELETE failed")
        return False


# =========================
# EXISTS
# =========================
async def safe_exists(key: str) -> bool:
    if redis_client is None:
        return False

    try:
        return await redis_client.exists(key) > 0
    except Exception:
        logger.exception("Redis EXISTS failed")
        return False


# =========================
# INCR (COUNTER)
# =========================
async def safe_incr(key: str, ex: int | None = None) -> int:
    if redis_client is None:
        return 0

    try:
        value = await redis_client.incr(key)

        if ex:
            await redis_client.expire(key, ex)

        return value

    except Exception:
        logger.exception("Redis INCR failed")
        return 0
