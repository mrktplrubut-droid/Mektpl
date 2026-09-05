import json

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from utils.media_sender import safe_copy_from_storage


# =========================
# FAVORITE + RATING
# =========================

def build_reaction_keyboard(code):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="❤️ Favorite", callback_data=f"favorite:{code}"),
                InlineKeyboardButton(text="⭐ Rating", callback_data=f"rating:{code}"),
            ]
        ]
    )


# =========================
# SEND ALL
# =========================

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

    try:
        status = await bot.send_message(chat_id, f"📤 Mengirim {total} media...\n\n0/{total}")
    except Exception:
        return False

    success = 0
    failed = 0

    for index, item in enumerate(media, start=1):
        if not isinstance(item, dict):
            failed += 1
            continue

        message_id = item.get("message_id")
        if not message_id:
            failed += 1
            continue

        result = await safe_copy_from_storage(
            bot, chat_id, message_id, protect_content=protect
        )

        if result is not None:
            success += 1
        else:
            failed += 1

        if index % 10 == 0 or index == total:
            try:
                text = f"📤 Mengirim media...\n\nBerhasil: {success}/{total}"
                if failed:
                    text += f"\nGagal: {failed}"
                await status.edit_text(text)
            except Exception:
                pass

    final_text = (
        f"✅ {success}/{total} Media Terkirim\n\n"
        "❤️ Simpan file ini ke favorit\n"
        "⭐ Berikan rating untuk membantu marketplace"
    )
    if failed:
        final_text = (
            f"✅ Berhasil: {success}/{total}\n"
            f"⚠️ Gagal: {failed}\n\n"
            "❤️ Simpan file ini ke favorit\n"
            "⭐ Berikan rating untuk membantu marketplace"
        )

    try:
        await status.edit_text(
            final_text,
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
