import json
from config import STORAGE_CHANNEL_ID


async def send_all(bot, chat_id, code, file, user_level):
    media = file["media"]

    # ✅ parse JSON aman
    if isinstance(media, str):
        try:
            media = json.loads(media)
        except:
            return False

    if not media:
        return False

    # ✅ default share_media
    share_media = file.get("share_media", True)

    # 🔥 LOGIC FINAL
    # VIP = tidak bisa forward
    # VVIP = bebas
    if user_level == "vip":
        protect = True
    else:
        protect = not share_media

    total = len(media)

    status = await bot.send_message(
        chat_id,
        f"📤 Mengirim {total} media..."
    )

    success = 0

    for index, item in enumerate(media, start=1):
        try:
            await bot.copy_message(
                chat_id=chat_id,
                from_chat_id=STORAGE_CHANNEL_ID,
                message_id=item["message_id"],
                protect_content=protect  # 🔥 KUNCI DI SINI
            )

            success += 1

            # update tiap 10 file
            if index % 10 == 0:
                try:
                    await status.edit_text(
                        f"📤 Mengirim media...\n\n{success}/{total}"
                    )
                except:
                    pass

        except Exception as e:
            print("SEND ALL ERROR:", e)

    try:
        await status.edit_text(
            f"✅ {success}/{total} Media Terkirim"
        )
    except:
        pass

    return True
