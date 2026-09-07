import asyncio
import json
import logging

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.exceptions import TelegramRetryAfter, TelegramBadRequest

from utils.media_sender import safe_copy_from_storage
from utils.share_unlock import telegram_setting

logger = logging.getLogger(__name__)

# Conservative user delivery pacing. One media -> wait -> next media.
SEND_INTERVAL = 3.0
PROGRESS_EDIT_INTERVAL = 0.75


def build_reaction_keyboard(code):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="❤️ Favorite", callback_data=f"favorite:{code}"),
                InlineKeyboardButton(text="⭐ Rating", callback_data=f"rating:{code}"),
            ]
        ]
    )


async def _edit_progress(status, text):
    try:
        await status.edit_text(text)
    except TelegramBadRequest as exc:
        if "message is not modified" not in str(exc).lower():
            logger.debug("SENDALL PROGRESS EDIT FAILED: %s", exc)
    except Exception:
        logger.debug("SENDALL PROGRESS EDIT ERROR", exc_info=True)


async def send_all(bot, chat_id, code, file, user_level):
    media = file.get("media")

    if isinstance(media, str):
        try:
            media = json.loads(media)
        except (json.JSONDecodeError, TypeError):
            return False

    if not isinstance(media, list) or not media:
        return False

    share_media = bool(file.get("share_media", True))
    protect = True if user_level == "vip" else not share_media
    total = len(media)
    send_interval = await telegram_setting("telegram_user_send_delay", SEND_INTERVAL)

    try:
        status = await bot.send_message(
            chat_id,
            f"📤 <b>Mengirim media</b>\n\n0/{total}\n⏱️ Jeda antar media: {send_interval:g} detik",
            parse_mode="HTML",
        )
    except Exception:
        return False

    success = 0
    failed = 0
    last_progress_edit = 0.0

    for index, item in enumerate(media, start=1):
        if not isinstance(item, dict):
            failed += 1
            continue

        message_id = item.get("message_id")
        if not message_id:
            failed += 1
            continue

        await _edit_progress(
            status,
            f"📤 <b>Mengirim media {index}/{total}...</b>\n\n"
            f"✅ Berhasil: {success}\n"
            f"⚠️ Gagal: {failed}\n\n"
            "🛡️ Pengiriman diperlambat untuk mengurangi risiko flood-limit Telegram.",
        )

        result = await safe_copy_from_storage(
            bot, chat_id, message_id, protect_content=protect
        )

        if result is not None:
            success += 1
        else:
            failed += 1

        # Exactly the requested pacing: after each item, wait 3 seconds
        # before requesting the next item. Telegram RetryAfter is handled
        # separately inside safe_copy_from_storage.
        if index < total:
            await asyncio.sleep(send_interval)

    final_text = (
        f"✅ <b>{success}/{total} Media Terkirim</b>\n\n"
        "❤️ Simpan file ini ke favorit\n"
        "⭐ Berikan rating untuk membantu marketplace"
    )
    if failed:
        final_text = (
            f"✅ <b>Berhasil: {success}/{total}</b>\n"
            f"⚠️ <b>Gagal: {failed}</b>\n\n"
            "Media yang gagal tidak di-retry otomatis agar bot tidak membanjiri Telegram.\n\n"
            "❤️ Simpan file ini ke favorit\n"
            "⭐ Berikan rating untuk membantu marketplace"
        )

    try:
        await status.edit_text(
            final_text,
            parse_mode="HTML",
            reply_markup=build_reaction_keyboard(code),
        )
    except Exception:
        try:
            await bot.send_message(
                chat_id,
                final_text,
                reply_markup=build_reaction_keyboard(code),
            )
        except Exception:
            pass

    return success > 0
