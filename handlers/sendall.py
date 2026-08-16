import json

from aiogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton
)

from config import STORAGE_CHANNEL_ID


# =========================
# FAVORITE + RATING
# =========================

def build_reaction_keyboard(code):

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="❤️ Favorite",
                    callback_data=f"favorite:{code}"
                ),
                InlineKeyboardButton(
                    text="⭐ Rating",
                    callback_data=f"rating:{code}"
                )
            ]
        ]
    )


# =========================
# SEND ALL
# =========================

async def send_all(
    bot,
    chat_id,
    code,
    file,
    user_level
):

    media = file["media"]


    # =========================
    # PARSE JSON
    # =========================

    if isinstance(media, str):

        try:

            media = json.loads(media)

        except Exception:

            return False


    if not media:

        return False


    # =========================
    # SHARE MEDIA
    # =========================

    share_media = file.get(
        "share_media",
        True
    )


    # =========================
    # PROTECT
    # =========================

    # VIP = tidak bisa forward
    # VVIP = mengikuti share_media

    if user_level == "vip":

        protect = True

    else:

        protect = not share_media


    total = len(media)


    # =========================
    # STATUS
    # =========================

    status = await bot.send_message(
        chat_id,
        f"📤 Mengirim {total} media..."
    )


    success = 0


    # =========================
    # SEND MEDIA
    # =========================

    for index, item in enumerate(
        media,
        start=1
    ):

        try:

            await bot.copy_message(
                chat_id=chat_id,
                from_chat_id=STORAGE_CHANNEL_ID,
                message_id=item["message_id"],
                protect_content=protect
            )


            success += 1


            # update tiap 10 file

            if index % 10 == 0:

                try:

                    await status.edit_text(
                        f"📤 Mengirim media...\n\n"
                        f"{success}/{total}"
                    )

                except:

                    pass


        except Exception as e:

            print(
                "SEND ALL ERROR:",
                e
            )


    # =========================
    # SELESAI
    # =========================

    try:

        await status.edit_text(
            f"✅ {success}/{total} Media Terkirim\n\n"
            "❤️ Simpan file ini ke favorit\n"
            "⭐ Berikan rating untuk membantu marketplace",
            reply_markup=build_reaction_keyboard(code)
        )

    except Exception as e:

        print(
            "SEND ALL STATUS ERROR:",
            e
        )

        # fallback kalau edit_text + keyboard gagal

        try:

            await bot.send_message(
                chat_id,
                "❤️ Favorite atau ⭐ Rating",
                reply_markup=build_reaction_keyboard(code)
            )

        except Exception as e2:

            print(
                "SEND ALL BUTTON ERROR:",
                e2
            )


    return True
