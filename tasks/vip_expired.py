import asyncio
import logging

from database import execute, fetch
from bot import bot
from config import PAYMENT_CHANNEL_ID

logger = logging.getLogger(__name__)


async def vip_expired_worker():
    logger.info("👑 VIP expired worker running...")
    while True:
        try:
            expired = await fetch("""
                UPDATE users
                SET vip=false, is_vip=false,
                    vip_until=NULL, vip_expired=NULL,
                    plan=CASE WHEN plan='vip' THEN 'free' ELSE plan END,
                    expired_at=NULL,
                    updated_at=NOW()
                WHERE (vip=true OR is_vip=true)
                  AND COALESCE(vip_expired, vip_until) IS NOT NULL
                  AND COALESCE(vip_expired, vip_until) <= NOW()
                RETURNING user_id
            """)
            for row in expired:
                uid = row["user_id"]
                try:
                    await execute(
                        """INSERT INTO user_notifications(user_id,type,title,message)
                           VALUES($1,'premium','VIP berakhir','Masa VIP kamu sudah berakhir. Untuk membuka code paid tanpa bayar lagi, silakan pilih paket VIP/Kreator kembali.')""",
                        uid
                    )
                    await bot.send_message(
                        uid,
                        "⌛ <b>VIP SUDAH BERAKHIR</b>\n\nMasa VIP kamu telah selesai. Akses premium dihentikan dan pembayaran per code berlaku lagi.\n\n💎 Pilih <b>VIP / Kreator</b> jika ingin mengaktifkan kembali.",
                        parse_mode="HTML"
                    )
                except Exception:
                    logger.exception("VIP expiry user notification failed user=%s", uid)
                try:
                    await bot.send_message(
                        PAYMENT_CHANNEL_ID,
                        f"⌛ <b>VIP EXPIRED</b>\n\n👤 User ID: <code>{uid}</code>\n🔒 Akses VIP dinonaktifkan otomatis.",
                        parse_mode="HTML"
                    )
                except Exception:
                    logger.exception("VIP expiry channel notification failed user=%s", uid)

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
