import asyncio
import logging

from database import execute

logger = logging.getLogger(__name__)


async def vip_expired_worker():
    logger.info("👑 VIP expired worker running...")
    while True:
        try:
            # Matikan VIP yang benar-benar sudah lewat masa aktif.
            result = await execute("""
                UPDATE users
                SET vip=false, is_vip=false,
                    vip_until=NULL, vip_expired=NULL,
                    plan=CASE WHEN plan='vip' THEN 'free' ELSE plan END,
                    expired_at=NULL,
                    updated_at=NOW()
                WHERE (vip=true OR is_vip=true)
                  AND COALESCE(vip_expired, vip_until) IS NOT NULL
                  AND COALESCE(vip_expired, vip_until) <= NOW()
            """)
            if result != "UPDATE 0":
                logger.info("VIP expired cleaned: %s", result)
            await execute("""
                UPDATE premium_payments
                SET status='expired'
                WHERE status='pending'
                  AND expires_at IS NOT NULL
                  AND expires_at <= NOW()
            """)
        except Exception:
            logger.exception("VIP expired worker error")
        await asyncio.sleep(300)
