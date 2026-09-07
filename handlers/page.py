import asyncio
import json
import time
from collections import defaultdict

from aiogram import Router, F
from aiogram.exceptions import TelegramRetryAfter
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
from utils.share_unlock import get_share_status, ensure_share_progress, gate_message


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
    file = await pool.fetchrow("SELECT * FROM files WHERE code=$1 LIMIT 1", code)
    if not file:
        return False

    from utils.user import get_user_status
    user_level = await get_user_status(pool, user_id)

    media = file["media"]
    if isinstance(media, str):
        try:
            media = json.loads(media)
        except Exception:
            return False
    if not isinstance(media, list) or not media:
        return False

    creator_access = await pool.fetchval(
        """SELECT COALESCE(is_creator,FALSE) AND COALESCE(creator_status,'none')='approved'
           FROM users WHERE user_id=$1""", user_id) or False
    owner_access = int(file["owner_id"] or 0) == int(user_id)
    purchase_access = await pool.fetchval(
        """SELECT EXISTS(SELECT 1 FROM file_purchases
           WHERE user_id=$1 AND file_code=$2 AND status='paid')""",
        user_id, code) or False
    free_access = await pool.fetchval(
        """SELECT EXISTS(SELECT 1 FROM free_code_progress
           WHERE user_id=$1 AND code=$2 AND completed=TRUE)""",
        user_id, code) or False
    privileged = bool(owner_access or purchase_access or creator_access or free_access or
                      user_level in ("vip", "vvip"))

    share_current, share_target, share_completed = await get_share_status(
        pool, code, user_id, is_paid=bool(file["is_paid"]), media_count=len(media))
    if not privileged and not share_completed:
        await ensure_share_progress(pool, code, user_id,
                                    is_paid=bool(file["is_paid"]), media_count=len(media))
        text, kb = await gate_message(
            bot, chat_id, code=code, title=str(file["title"] or code),
            progress=share_current, target=share_target,
            is_paid=bool(file["is_paid"]))
        await bot.send_message(chat_id, text, parse_mode="HTML", reply_markup=kb)
        return False

    total_pages = max(1, (len(media) + PAGE_SIZE - 1) // PAGE_SIZE)
    page = max(1, min(int(page), total_pages))
    start = (page - 1) * PAGE_SIZE
    chunk = media[start:start + PAGE_SIZE]

    # Unique view only on first page.
    if page == 1:
        viewed = await pool.fetchrow(
            """INSERT INTO file_views(user_id,file_code) VALUES($1,$2)
               ON CONFLICT(user_id,file_code) DO NOTHING RETURNING user_id""",
            user_id, code)
        if viewed:
            await pool.execute(
                """UPDATE files SET views=COALESCE(views,0)+1,
                   view_count=COALESCE(view_count,0)+1 WHERE code=$1""", code)

    share_media = file["share_media"]
    protect = not bool(True if share_media is None else share_media)

    # Album = max 10 Telegram media. This is intentionally one album per page.
    album = []
    caption = (
        f"🔑 <b>CODE:</b> <code>{code}</code>\n"
        f"🤖 <b>BOT:</b> @{(await bot.get_me()).username or 'bot'}\n"
        f"📦 <b>MEDIA:</b> {start + 1}-{start + len(chunk)} / {len(media)}\n"
        f"📄 <b>PAGE:</b> {page}/{total_pages}"
    )
    for idx, item in enumerate(chunk):
        if not isinstance(item, dict) or not item.get("file_id"):
            continue
        fid = item["file_id"]
        typ = normalize_type(item.get("type"))
        cap = caption if not album else None
        if typ == "photo":
            album.append(InputMediaPhoto(media=fid, caption=cap))
        elif typ == "video":
            album.append(InputMediaVideo(media=fid, caption=cap))
        else:
            album.append(InputMediaDocument(media=fid, caption=cap))
    if not album:
        return False

    try:
        await bot.send_media_group(chat_id=chat_id, media=album, protect_content=protect)
    except TelegramRetryAfter as exc:
        await asyncio.sleep(max(float(exc.retry_after), 1.0) + 0.5)
        return False
    except Exception:
        return False

    # Compact status bubble: e.g. 1/4 for a 40-media code.
    status = await bot.send_message(
        chat_id,
        f"📦 <b>{page}/{total_pages}</b> media page • "
        f"<b>{len(album)}/{len(chunk)}</b> terkirim • Total <b>{len(media)}</b>",
        parse_mode="HTML",
    )

    # Navigation is deliberately not auto-advanced. The next page requires a
    # button press and the handler enforces a 5-second cooldown.
    keyboard = [
        build_page_buttons(code, page, total_pages),
        [
            InlineKeyboardButton(text="👍 Like", callback_data=f"like:{code}"),
            InlineKeyboardButton(text="👎 No Like", callback_data=f"dislike:{code}"),
        ],
        [
            InlineKeyboardButton(text="❤️ Favorit", callback_data=f"favorite:{code}"),
            InlineKeyboardButton(text="⭐ Rating", callback_data=f"rating:{code}"),
        ],
        [
            InlineKeyboardButton(text="🛍️ Marketplace", callback_data="marketplace"),
            InlineKeyboardButton(text="🔍 Cari Code", callback_data="search_code"),
        ],
        [InlineKeyboardButton(text="📤 Send All", callback_data=f"all:{code}")],
    ]
    try:
        await status.edit_reply_markup(reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard))
    except Exception:
        pass

    NAV_CACHE[(user_id, code)] = status.message_id
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

        # Minimum 5 seconds between page requests for the same code.
        nav_key = (user_id, code)
        now = time.time()
        last = PAGE_CHANGE.get(nav_key, 0.0)
        if last and now - last < 5.0:
            remaining = 5.0 - (now - last)
            return await call.answer(
                f"⏳ Tunggu {remaining:.1f} detik sebelum membuka page berikutnya.",
                show_alert=True,
            )
        PAGE_CHANGE[nav_key] = now

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
