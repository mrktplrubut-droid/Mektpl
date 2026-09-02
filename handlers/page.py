import math
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

SAME_PAGE_COOLDOWN = 3600
CHANGE_PAGE_COOLDOWN = 30

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

                if now - value[0] > 7200:
                    remove.append(key)

            for key in remove:
                del cache[key]


def clean_file_id(fid):
    return fid.get("file_id") if isinstance(fid, dict) else fid


def normalize_type(ftype):
    return (ftype or "document").lower()


# =========================
# FAVORITE + RATING BUTTON
# =========================

def build_reaction_buttons(code):

    return [
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


# =========================
# SEND PAGE
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


    # =========================
    # AKSES + VIEW REAL DATABASE
    # =========================
    creator_access = await pool.fetchval(
        """
        SELECT COALESCE(is_creator, FALSE)
               AND COALESCE(creator_status, 'none') = 'approved'
        FROM users WHERE user_id=$1
        """, user_id
    ) or False
    owner_access = (file["owner_id"] == user_id)
    purchase_access = await pool.fetchval(
        """SELECT EXISTS(SELECT 1 FROM file_purchases
           WHERE user_id=$1 AND file_code=$2 AND status='paid')""",
        user_id, code
    ) or False
    free_access = await pool.fetchval(
        """SELECT EXISTS(SELECT 1 FROM free_code_progress
           WHERE user_id=$1 AND code=$2 AND completed=TRUE)""",
        user_id, code
    ) or False
    if bool(file["is_paid"]) and not (creator_access or owner_access or purchase_access or free_access):
        await bot.send_message(
            chat_id,
            "🔒 <b>FILE BERBAYAR</b>\n\n"
            f"💰 Harga: <b>Rp {int(file['price'] or 0):,}</b>\n\n"
            "Silakan beli file untuk membukanya.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="💳 Beli", callback_data=f"pay:{code}")
            ]])
        )
        return False

    if page == 1:
        viewed = await pool.fetchrow(
            """INSERT INTO file_views(user_id,file_code) VALUES($1,$2)
               ON CONFLICT(user_id,file_code) DO NOTHING RETURNING user_id""",
            user_id, code
        )
        if viewed:
            await pool.execute(
                """UPDATE files SET views=COALESCE(views,0)+1,
                   view_count=COALESCE(view_count,0)+1 WHERE code=$1""", code
            )


    # =========================
    # MEDIA
    # =========================

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


    # =========================
    # BUILD ALBUM
    # =========================

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


    # =========================
    # SEND MEDIA
    # =========================

    try:

        if len(album) == 1:

            item = chunk[0]

            file_id = item.get("file_id")
            media_type = item.get(
                "type",
                "document"
            ).lower()


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


    # =========================
    # NAVIGATION
    # =========================

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
            ],

            # ❤️ FAVORITE + ⭐ RATING
            *build_reaction_buttons(code)

        ]
    )


    nav = await bot.send_message(
        chat_id,
        (
            f"📦 PAGE {page}/{total_page}\n"
            f"✅ {len(album)}/{len(chunk)} Media\n\n"
            "❤️ Simpan ke favorit atau ⭐ berikan rating"
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
# PAGE BUTTONS
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

        emoji = (
            "🔲"
            if i == page
            else (
                "▫️"
                if i < page
                else "▪️"
            )
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
# PAGE HANDLER
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


# =========================
# END PAGE
# =========================

@router.callback_query(F.data == "end_page")
async def end_page(call: CallbackQuery):

    try:

        await call.answer(
            "📄 Semua file sudah ditampilkan.",
            show_alert=True
        )

    except:
        pass

@router.callback_query(F.data.startswith("all:"))
async def open_all_pages(call: CallbackQuery):
    code=call.data.split(":",1)[1]; user_id=call.from_user.id
    pool=await get_pool(); file=await pool.fetchrow("SELECT media,is_paid,price FROM files WHERE code=$1",code)
    if not file: return await call.answer("File tidak ditemukan.",show_alert=True)
    # send_page enforces paid access before any media is sent.
    try:
        media=file["media"]
        if isinstance(media,str): media=json.loads(media)
        total=max(1, math.ceil(len(media or [])/PAGE_SIZE))
    except Exception: return await call.answer("Media tidak valid.",show_alert=True)
    await call.answer("📤 Mengirim semua halaman..." if total>1 else "📤 Membuka file...")
    for p in range(1,total+1):
        ok=await send_page(call.bot,call.message.chat.id,user_id,code,p)
        if not ok: break
