"""Safe paginated Send All delivery.
Each batch contains at most 10 media, followed by a manual Continue/Stop choice.
"""
import asyncio, json, logging
from aiogram import Router, F
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.exceptions import TelegramRetryAfter
from utils.media_sender import safe_copy_from_storage
from utils.share_unlock import telegram_setting

logger = logging.getLogger(__name__)
SEND_INTERVAL = 3.0
BATCH_SIZE = 10

def final_keyboard(code):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👍 Like", callback_data=f"like:{code}"),
         InlineKeyboardButton(text="👎 No Like", callback_data=f"dislike:{code}")],
        [InlineKeyboardButton(text="❤️ Favorit", callback_data=f"favorite:{code}"),
         InlineKeyboardButton(text="⭐ Rating", callback_data=f"rating:{code}")],
        [InlineKeyboardButton(text="🛍️ Marketplace", callback_data="marketplace"),
         InlineKeyboardButton(text="🔍 Cari Code", callback_data="search_code")],
    ])

def continue_keyboard(code, next_offset):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="▶️ Lanjut Kirim", callback_data=f"allnext:{code}:{next_offset}")],
        [InlineKeyboardButton(text="⛔ Stop Kirim", callback_data=f"allstop:{code}")],
    ])

async def send_all(bot, chat_id, code, file, user_level, offset=0, status_message=None):
    media = file.get("media")
    if isinstance(media, str):
        try: media = json.loads(media)
        except Exception: return False
    if not isinstance(media, list) or not media: return False

    total = len(media)
    offset = max(0, min(int(offset), total))
    if offset >= total:
        msg = "✅ <b>Semua media sudah terkirim.</b>"
        if status_message:
            try: await status_message.edit_text(msg, parse_mode="HTML", reply_markup=final_keyboard(code))
            except Exception: pass
        else:
            await bot.send_message(chat_id, msg, parse_mode="HTML", reply_markup=final_keyboard(code))
        return True

    send_interval = await telegram_setting("telegram_user_send_delay", SEND_INTERVAL)
    batch_end = min(offset + BATCH_SIZE, total)
    batch = media[offset:batch_end]
    me = await bot.get_me()
    bot_name = f"@{me.username}" if me.username else "bot"

    if status_message is None:
        status_message = await bot.send_message(
            chat_id,
            f"⏳ <b>Send All</b> • Media {offset+1}-{batch_end}/{total}\n"
            f"🛡️ Jeda {send_interval:g} detik/media",
            parse_mode="HTML",
        )
    else:
        try:
            await status_message.edit_text(
                f"⏳ <b>Send All</b> • Media {offset+1}-{batch_end}/{total}\n"
                f"🛡️ Jeda {send_interval:g} detik/media",
                parse_mode="HTML")
        except Exception: pass

    success = 0
    failed = 0
    share_media = file.get("share_media", True)
    protect = not bool(share_media)

    for pos, item in enumerate(batch, start=offset + 1):
        if not isinstance(item, dict):
            failed += 1
            continue
        message_id = item.get("message_id")
        if not message_id:
            failed += 1
            continue

        # Every media gets a compact code/bot/index header before the copied media.
        try:
            await bot.send_message(
                chat_id,
                f"🔑 <code>{code}</code> • 🤖 {bot_name} • 📦 <b>Media {pos}/{total}</b>",
                parse_mode="HTML",
            )
        except Exception:
            pass

        try:
            result = await safe_copy_from_storage(
                bot, chat_id, message_id, protect_content=protect,
                delay=0.0)
            if result is not None:
                success += 1
            else:
                failed += 1
        except TelegramRetryAfter as exc:
            await asyncio.sleep(max(float(exc.retry_after), 1.0) + 0.5)
            failed += 1
        except Exception:
            failed += 1

        if pos < batch_end:
            await asyncio.sleep(send_interval)

    remaining = total - batch_end
    if remaining > 0:
        text = (
            f"📦 <b>Batch selesai: {offset+1}-{batch_end}/{total}</b>\n"
            f"✅ Berhasil: {success} • ⚠️ Gagal: {failed}\n\n"
            f"⏭️ Masih ada <b>{remaining}</b> media.\n"
            "Pilih <b>Lanjut Kirim</b> untuk batch berikutnya atau <b>Stop</b>."
        )
        try:
            await status_message.edit_text(text, parse_mode="HTML",
                                           reply_markup=continue_keyboard(code, batch_end))
        except Exception:
            await bot.send_message(chat_id, text, parse_mode="HTML",
                                   reply_markup=continue_keyboard(code, batch_end))
        return success > 0

    final_text = f"✅ <b>Send All selesai</b>\n\n📦 {success}/{total} media terkirim"
    if failed: final_text += f"\n⚠️ Gagal: {failed}"
    final_text += "\n\nSemua media sudah dikirim."
    try:
        await status_message.edit_text(final_text, parse_mode="HTML",
                                       reply_markup=final_keyboard(code))
    except Exception:
        await bot.send_message(chat_id, final_text, parse_mode="HTML",
                               reply_markup=final_keyboard(code))
    return success > 0

async def _load_file(code):
    from database import get_pool
    pool = await get_pool()
    return await pool.fetchrow("SELECT * FROM files WHERE code=$1 LIMIT 1", code)

async def _can_open(pool, file, user_id):
    from utils.user import get_user_status
    level = await get_user_status(pool, user_id)
    if int(file.get("owner_id") or 0) == int(user_id) or level in ("vip","vvip"):
        return True, level
    paid = await pool.fetchval("""SELECT EXISTS(
        SELECT 1 FROM file_purchases WHERE user_id=$1 AND file_code=$2 AND status='paid')""",
        user_id, file["code"])
    creator = await pool.fetchval("""SELECT COALESCE(is_creator,FALSE)
        AND COALESCE(creator_status,'none')='approved' FROM users WHERE user_id=$1""", user_id)
    return bool(paid or creator), level

router = Router()

@router.callback_query(F.data.startswith("allnext:"))
async def all_next(call):
    await call.answer("⏳ Melanjutkan pengiriman...")
    _, code, offset = call.data.split(":", 2)
    file = await _load_file(code)
    if not file: return await call.answer("❌ Code tidak ditemukan.", show_alert=True)
    from database import get_pool
    pool = await get_pool()
    allowed, level = await _can_open(pool, file, call.from_user.id)
    if not allowed:
        return await call.answer("❌ Akses tidak tersedia.", show_alert=True)
    await send_all(call.bot, call.message.chat.id, code, file, level, int(offset), call.message)

@router.callback_query(F.data.startswith("allstop:"))
async def all_stop(call):
    await call.answer("⛔ Pengiriman dihentikan.")
    code = call.data.split(":",1)[1]
    try:
        await call.message.edit_text(
            f"⛔ <b>Send All dihentikan.</b>\n\n🔑 <code>{code}</code>",
            parse_mode="HTML", reply_markup=final_keyboard(code))
    except Exception: pass
