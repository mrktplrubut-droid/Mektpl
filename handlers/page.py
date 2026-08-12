import asyncio
import json
import time
from collections import defaultdict

from aiogram import Router, F
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton
)
from aiogram.types import (
    InputMediaPhoto,
    InputMediaVideo,
    InputMediaDocument
)

from database import get_pool
from config import STORAGE_CHANNEL_ID


router = Router()

PAGE_SIZE = 10

SAME_PAGE_COOLDOWN = 3600      # 1 jam
CHANGE_PAGE_COOLDOWN = 30      # 30 detik

USER_LOCK = defaultdict(lambda: asyncio.Lock())

PAGE_CACHE = {}
PAGE_CHANGE = {}
NAV_CACHE = {}

# =========================
# UTIL
# =========================
async def clear_cache_loop():

    while True:

        await asyncio.sleep(3600)

        now = time.time()

        for cache in [PAGE_CACHE, PAGE_CHANGE]:

            remove = []

            for key, value in list(cache.items()):

                if now - value[1] > 7200:
                    remove.append(key)

            for key in remove:
                del cache[key]
                
def clean_file_id(fid):
    return fid.get("file_id") if isinstance(fid, dict) else fid


def normalize_type(ftype):
    return (ftype or "document").lower()


# =========================
# SEND PAGE (REUSABLE CORE)
# =========================
async def send_page(bot, chat_id, user_id, code, page=1):

    pool = await get_pool()

    file = await pool.fetchrow(
        """
        SELECT *
        FROM files
        WHERE code=$1
        LIMIT 1
        """,
        code
    )

    if not file:
        print("FILE NOT FOUND")
        return False


    media = file["media"]

    if isinstance(media, str):
        try:
            media = json.loads(media)
        except Exception as e:
            print("MEDIA JSON ERROR", e)
            return False


    if not media:
        print("MEDIA EMPTY")
        return False


    total_page = (
        len(media) + PAGE_SIZE - 1
    ) // PAGE_SIZE


    page = max(
        1,
        min(page, total_page)
    )


    start = (page - 1) * PAGE_SIZE
    end = start + PAGE_SIZE

    chunk = media[start:end]


    share_media = file["share_media"]

    if share_media is None:
        share_media = True


    protect = not share_media


    caption = (
        "botmarketRobot\n"
        "━━━━━━━━━━━━━━━\n\n"
        f"🔑 CODE : {code}\n"
        f"📦 PAGE : {page}/{total_page}\n"
        f"📊 TOTAL : {len(media)} FILE"
    )


    album = []


    for index, item in enumerate(chunk):

        if not isinstance(item, dict):
            continue


        file_id = item.get("file_id")

        if not file_id:
            continue


        media_type = (
            item.get("type")
            or "document"
        ).lower()


        cap = caption if index == 0 else None


        if media_type == "photo":

            album.append(
                InputMediaPhoto(
                    media=file_id,
                    caption=cap
                )
            )


        elif media_type == "video":

            album.append(
                InputMediaVideo(
                    media=file_id,
                    caption=cap
                )
            )


        else:

            album.append(
                InputMediaDocument(
                    media=file_id,
                    caption=cap
                )
            )


    if not album:
        print("ALBUM EMPTY")
        return False



    try:

        if len(album) == 1:

            item = chunk[0]

            file_id = item.get("file_id")
            media_type = item.get("type", "document").lower()

            if media_type == "photo":

                await bot.send_photo(
                    chat_id,
                    file_id,
                    caption=caption,
                    protect_content=protect
                )

            elif media_type == "video":

                await bot.send_video(
                    chat_id,
                    file_id,
                    caption=caption,
                    protect_content=protect
                )

            else:

                await bot.send_document(
                    chat_id,
                    file_id,
                    caption=caption,
                    protect_content=protect
                )

        else:

            await bot.send_media_group(
                chat_id,
                album,
                protect_content=protect
            )


            if protect:

                await bot.send_message(
                    chat_id,
                    "🔒 File dilindungi"
                )


    except Exception as e:

        print(
            "SEND MEDIA ERROR",
            e
        )

        return False



    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[

            build_page_buttons(
                code,
                page,
                total_page
            ),

            [
                InlineKeyboardButton(
                    text="📤 OPEN ALL",
                    callback_data=f"all:{code}"
                )
            ]

        ]
    )


    nav = await bot.send_message(
        chat_id,
        (
            f"📦 PAGE {page}/{total_page}\n"
            f"✅ {len(album)}/{len(chunk)} Media"
        ),
        reply_markup=keyboard
    )


    NAV_CACHE[
        (user_id, code)
    ] = nav.message_id


    print(
        "PAGE SENT",
        code,
        page,
        len(album)
    )


    return True


# =========================
# BUTTON
# =========================
def build_page_buttons(code: str, page: int, total: int):

    row = []


    # PREV
    if page > 1:
        row.append(
            InlineKeyboardButton(
                text="⬅️ Prev",
                callback_data=f"page:{code}:{page-1}"
            )
        )


    # NOMOR HALAMAN
    start = max(1, page - 2)
    end = min(total, page + 2)

    for i in range(start, end + 1):

        emoji = "🔲" if i == page else (
            "▫️" if i < page else "▪️"
        )

        row.append(
            InlineKeyboardButton(
                text=f"{i}{emoji}",
                callback_data=f"page:{code}:{i}"
            )
        )


    # NEXT
    if page < total:

        row.append(
            InlineKeyboardButton(
                text="Next ➡️",
                callback_data=f"page:{code}:{page+1}"
            )
        )

    else:

        row.append(
            InlineKeyboardButton(
                text="✅ END",
                callback_data="end_page"
            )
        )


    return row


# =========================
# HANDLER
# =========================
@router.callback_query(F.data.startswith("page:"))
async def page_handler(call: CallbackQuery):

    user_id = call.from_user.id


    try:
        await call.answer("📂 Loading...")
    except:
        pass


    try:

        _, code, page = call.data.split(":")
        page = int(page)

    except Exception:

        return await call.answer(
            "❌ Data halaman rusak",
            show_alert=True
        )



    async with USER_LOCK[user_id]:


        # =========================
        # HAPUS NAV LAMA
        # =========================

        old_nav = NAV_CACHE.get(
            (user_id, code)
        )


        if old_nav:

            try:

                await call.bot.delete_message(
                    call.message.chat.id,
                    old_nav
                )

            except:
                pass


            NAV_CACHE.pop(
                (user_id, code),
                None
            )



        # =========================
        # SEND PAGE
        # =========================

        result = await send_page(
            bot=call.bot,
            chat_id=call.message.chat.id,
            user_id=user_id,
            code=code,
            page=page
        )


        if not result:

            try:
                await call.answer(
                    "❌ Gagal membuka halaman",
                    show_alert=True
                )
            except:
                pass



@router.callback_query(F.data=="end_page")
async def end_page(call: CallbackQuery):

    try:

        await call.answer(
            "📄 Semua file sudah ditampilkan.",
            show_alert=True
        )

    except:
        pass
