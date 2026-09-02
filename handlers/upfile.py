import asyncio
import json
import logging
import random
import re
import time

from contextlib import asynccontextmanager
from typing import Dict, Optional

from aiogram import Router, F
from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import CHANNEL_ID, STORAGE_CHANNEL_ID
from database import get_pool
from keyboards.join import join_kb
from utils.force_sub import check_force_sub


router = Router()


# =========================================================
# CONFIG
# =========================================================

MAX_MEDIA = 200
MAX_REVIEW_PHOTOS = 5

UPDATE_DELAY = 0.5
COPY_DELAY = 0.2

REVIEW_CHANNEL_ID = -1003984536150


# =========================================================
# LOGGING
# =========================================================

logger = logging.getLogger(__name__)


# =========================================================
# LOCKS
# =========================================================

_last_update: Dict[int, float] = {}
_user_locks: Dict[int, asyncio.Lock] = {}

_copy_lock = asyncio.Lock()


def get_lock(user_id: int) -> asyncio.Lock:

    if user_id not in _user_locks:
        _user_locks[user_id] = asyncio.Lock()

    return _user_locks[user_id]


@asynccontextmanager
async def user_lock(user_id: int):

    async with get_lock(user_id):
        yield


# =========================================================
# UPLOAD STATE
# =========================================================

class UploadState(StatesGroup):

    upload = State()

    wait_title = State()

    wait_price = State()

    wait_review = State()


# =========================================================
# BAD WORD FILTER
# =========================================================

BAD_WORDS = {
    "bocil",
    "child",
    "underage",
    "minor",
}


def normalize(text: str) -> str:

    return re.sub(
        r"[^a-z0-9]",
        "",
        (text or "").lower()
    )


def is_bad(text: str) -> bool:

    clean = normalize(text)

    return any(
        word in clean
        for word in BAD_WORDS
    )


# =========================================================
# USER LOCK / SAFE UPDATE
# =========================================================

async def safe_update(
    bot,
    chat_id: int,
    message_id: int,
    text: str,
    reply_markup=None,
):
    """
    Update pesan progress dengan throttle
    agar tidak terkena flood Telegram.
    """

    now = time.monotonic()

    last = _last_update.get(chat_id, 0)

    if now - last < UPDATE_DELAY:
        return

    _last_update[chat_id] = now

    try:

        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=text,
            parse_mode="HTML",
            reply_markup=reply_markup,
        )

    except TelegramBadRequest:
        # Bisa terjadi kalau text sama / message sudah berubah.
        pass

    except Exception:

        logger.exception(
            "SAFE UPDATE ERROR | chat=%s | message=%s",
            chat_id,
            message_id,
        )


# =========================================================
# COPY FILE TO STORAGE CHANNEL
# =========================================================

async def copy_to_storage(
    bot,
    from_chat_id: int,
    message_id: int,
):

    async with _copy_lock:

        while True:

            try:

                copied = await bot.copy_message(
                    chat_id=STORAGE_CHANNEL_ID,
                    from_chat_id=from_chat_id,
                    message_id=message_id,
                )

                await asyncio.sleep(COPY_DELAY)

                return copied

            except TelegramRetryAfter as e:

                logger.warning(
                    "TelegramRetryAfter STORAGE | retry=%s",
                    e.retry_after,
                )

                await asyncio.sleep(
                    e.retry_after + 1
                )

            except Exception:

                logger.exception(
                    "COPY STORAGE ERROR"
                )

                raise


# =========================================================
# GENERATE UNIQUE CODE
# =========================================================

async def generate_code() -> str:

    pool = await get_pool()

    chars = "0123456789aiueo"

    while True:

        code = "".join(
            random.choices(
                chars,
                k=40,
            )
        )

        exists = await pool.fetchval(
            """
            SELECT 1
            FROM files
            WHERE code = $1
            LIMIT 1
            """,
            code,
        )

        if not exists:
            return code


# =========================================================
# FORMAT RUPIAH
# =========================================================

def rupiah(amount: int) -> str:

    return f"Rp{amount:,}".replace(",", ".")


# =========================================================
# FORMAT USER ID
# =========================================================

def mask_user_id(user_id: int) -> str:

    value = str(user_id)

    if len(value) <= 4:
        return value

    return (
        value[:2]
        + "****"
        + value[-2:]
    )


# =========================================================
# MEDIA KEYBOARD
# =========================================================

def upload_keyboard():

    kb = InlineKeyboardBuilder()

    kb.button(
        text="⏹ STOP & SAVE",
        callback_data="save_upfile",
    )

    kb.button(
        text="❌ BATAL",
        callback_data="cancel_upfile",
    )

    kb.adjust(1)

    return kb.as_markup()


# =========================================================
# REVIEW KEYBOARD
# =========================================================

def review_keyboard():

    kb = InlineKeyboardBuilder()

    kb.button(
        text="✅ SELESAI REVIEW",
        callback_data="finish_review",
    )

    kb.button(
        text="❌ BATAL",
        callback_data="cancel_upfile",
    )

    kb.adjust(1)

    return kb.as_markup()


# =========================================================
# START UPLOAD
# =========================================================

@router.callback_query(
    F.data == "upfile"
)
async def start_upload(
    call: CallbackQuery,
    state: FSMContext,
):

    await call.answer()

    user_id = call.from_user.id

    # -----------------------------------------------------
    # FORCE SUB
    # -----------------------------------------------------

    if not await check_force_sub(
        call.bot,
        user_id,
    ):

        return await call.message.answer(
            "❌ Kamu belum join channel.",
            reply_markup=join_kb(),
        )

    # -----------------------------------------------------
    # CHECK CREATOR
    # -----------------------------------------------------

    pool = await get_pool()

    creator = await pool.fetchrow(
        """
        SELECT
            is_creator,
            creator_status
        FROM users
        WHERE user_id = $1
        """,
        user_id,
    )

    is_creator = bool(
        creator
        and creator["is_creator"]
        and creator["creator_status"] == "approved"
    )

    # -----------------------------------------------------
    # RESET STATE
    # -----------------------------------------------------

    await state.clear()

    await state.set_state(
        UploadState.upload
    )

    # -----------------------------------------------------
    # SAVE USER INFO TO STATE
    # -----------------------------------------------------

    await state.update_data(

        upload_mode=True,

        media=[],

        title=None,

        share_media=True,

        is_paid=False,

        price=0,

        payment_provider=None,

        review_photos=[],

        saving=False,

        progress_msg_id=None,

        saving_msg_id=None,

        is_creator=is_creator,

        creator_id=user_id,

        creator_username=call.from_user.username,

        creator_fullname=(
            call.from_user.full_name
            or "Unknown"
        ),
    )

    # -----------------------------------------------------
    # TEXT
    # -----------------------------------------------------

    text = (
        "📦 <b>UPLOAD MODE</b>\n\n"
        "Silakan kirim file.\n"
        f"Maksimal <b>{MAX_MEDIA}</b> media.\n\n"
    )

    if is_creator:

        text += (
            "🎨 Status : "
            "<b>Kreator Terverifikasi</b> ✅\n\n"

            "Kamu dapat membuat:\n"
            "🆓 File FREE\n"
            "💰 File PAID\n\n"
        )

    else:

        text += (
            "👤 Status : <b>User</b>\n\n"

            "🆓 Kamu dapat membuat file FREE.\n"

            "🔒 File PAID hanya dapat dibuat "
            "oleh Kreator terverifikasi.\n\n"
        )

    text += (
        "Kirim file satu per satu.\n"
        "Jika selesai tekan <b>STOP & SAVE</b>."
    )

    # -----------------------------------------------------
    # EDIT PROGRESS
    # -----------------------------------------------------

    try:

        await call.message.edit_text(
            text,
            parse_mode="HTML",
            reply_markup=upload_keyboard(),
        )

        progress_id = call.message.message_id

    except Exception:

        msg = await call.message.answer(
            text,
            parse_mode="HTML",
            reply_markup=upload_keyboard(),
        )

        progress_id = msg.message_id

    # -----------------------------------------------------
    # SAVE PROGRESS MESSAGE ID
    # -----------------------------------------------------

    await state.update_data(
        progress_msg_id=progress_id
    )


# =========================================================
# RECEIVE MEDIA
# =========================================================

@router.message(
    UploadState.upload,
    F.document
    | F.video
    | F.photo
)
async def receive_media(
    message: Message,
    state: FSMContext,
):

    user_id = message.from_user.id

    async with user_lock(user_id):

        data = await state.get_data()

        # -------------------------------------------------
        # CHECK UPLOAD MODE
        # -------------------------------------------------

        if not data.get("upload_mode"):
            return

        media = data.get(
            "media",
            []
        )

        # -------------------------------------------------
        # MAX MEDIA
        # -------------------------------------------------

        if len(media) >= MAX_MEDIA:

            return await message.answer(
                f"❌ Maksimal {MAX_MEDIA} media."
            )

        # -------------------------------------------------
        # CREATOR STATUS
        # -------------------------------------------------

        is_creator = bool(
            data.get(
                "is_creator",
                False
            )
        )

        # -------------------------------------------------
        # GET FILE DATA
        # -------------------------------------------------

        file_id = None
        file_type = None
        file_name = None
        file_size = 0

        if message.document:

            file_type = "document"

            file_id = message.document.file_id

            file_name = (
                message.document.file_name
            )

            file_size = (
                message.document.file_size
                or 0
            )

        elif message.video:

            file_type = "video"

            file_id = message.video.file_id

            file_name = getattr(
                message.video,
                "file_name",
                None,
            )

            file_size = (
                message.video.file_size
                or 0
            )

        elif message.photo:

            file_type = "photo"

            file_id = (
                message.photo[-1].file_id
            )

            file_size = (
                message.photo[-1].file_size
                or 0
            )

        if not file_id:
            return

        # -------------------------------------------------
        # DUPLICATE CHECK
        # -------------------------------------------------

        if any(
            item.get("file_id") == file_id
            for item in media
        ):

            try:
                await message.delete()
            except Exception:
                pass

            return await message.answer(
                "⚠️ File tersebut sudah ditambahkan."
            )

        # -------------------------------------------------
        # STORAGE
        # -------------------------------------------------

        storage_message_id = None

        if is_creator:

            try:

                copied = await copy_to_storage(
                    message.bot,
                    message.chat.id,
                    message.message_id,
                )

                storage_message_id = (
                    copied.message_id
                )

            except Exception:

                logger.exception(
                    "CREATOR STORAGE ERROR | user=%s",
                    user_id,
                )

                return await message.answer(
                    "⚠️ Gagal menyimpan file ke storage.\n"
                    "Silakan coba lagi."
                )

        # -------------------------------------------------
        # APPEND MEDIA
        # -------------------------------------------------

        media.append({

            "message_id": storage_message_id,

            "file_id": file_id,

            "type": file_type,

            "file_name": file_name,

            "file_size": file_size,

            "position": len(media) + 1,
        })

        await state.update_data(
            media=media
        )

        # -------------------------------------------------
        # UPDATE PROGRESS
        # -------------------------------------------------

        progress_id = data.get(
            "progress_msg_id"
        )

        if progress_id:

            storage_text = (
                "☁️ Storage Channel"
                if is_creator
                else "🆔 Telegram File ID"
            )

            await safe_update(

                message.bot,

                message.chat.id,

                progress_id,

                (
                    "📦 <b>UPLOAD MODE</b>\n\n"

                    f"📁 Media : "
                    f"<b>{len(media)}/{MAX_MEDIA}</b>\n"

                    f"💾 Penyimpanan : "
                    f"<b>{storage_text}</b>\n\n"

                    "Kirim media lagi atau tekan "
                    "<b>STOP & SAVE</b>."
                ),

                upload_keyboard(),
            )

        # -------------------------------------------------
        # DELETE USER MESSAGE
        # -------------------------------------------------

        try:
            await message.delete()
        except Exception:
            pass


# =========================================================
# CANCEL UPLOAD
# =========================================================

@router.callback_query(
    F.data == "cancel_upfile"
)
async def cancel_upload(
    call: CallbackQuery,
    state: FSMContext,
):

    await call.answer()

    user_id = call.from_user.id

    async with user_lock(user_id):

        data = await state.get_data()

        progress_id = data.get(
            "progress_msg_id"
        )

        saving_id = data.get(
            "saving_msg_id"
        )

        # -------------------------------------------------
        # DELETE PROGRESS
        # -------------------------------------------------

        for message_id in (
            progress_id,
            saving_id,
        ):

            if not message_id:
                continue

            try:

                await call.bot.delete_message(
                    chat_id=call.message.chat.id,
                    message_id=message_id,
                )

            except Exception:
                pass

        # -------------------------------------------------
        # CLEAR STATE
        # -------------------------------------------------

        await state.clear()

        # -------------------------------------------------
        # RESPONSE
        # -------------------------------------------------

        try:

            await call.message.edit_text(
                "❌ <b>Upload dibatalkan.</b>",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            InlineKeyboardButton(
                                text="🏠 Home",
                                callback_data="home",
                            )
                        ]
                    ]
                ),
            )

        except Exception:

            await call.message.answer(
                "❌ <b>Upload dibatalkan.</b>",
                parse_mode="HTML",
            )


# =========================================================
# CHOOSE SHARE MODE
# =========================================================

@router.callback_query(
    F.data == "save_upfile"
)
async def choose_share_mode(
    call: CallbackQuery,
    state: FSMContext,
):

    await call.answer()

    user_id = call.from_user.id

    async with user_lock(user_id):

        data = await state.get_data()

        if not data.get("upload_mode"):

            return await call.answer(
                "❌ Sesi upload sudah berakhir.",
                show_alert=True,
            )

        media = data.get(
            "media",
            []
        )

        if not media:

            return await call.answer(
                "❌ Belum ada media.",
                show_alert=True,
            )

        kb = InlineKeyboardBuilder()

        kb.button(
            text="🔗 Share Media",
            callback_data="share_yes",
        )

        kb.button(
            text="🔒 Private",
            callback_data="share_no",
        )

        kb.adjust(2)

        await call.message.edit_text(

            "📦 <b>PILIH MODE FILE</b>\n\n"

            "🔗 <b>Share Media</b>\n"
            "File bisa dibuka melalui link.\n\n"

            "🔒 <b>Private</b>\n"
            "File hanya dapat dibuka melalui code.",

            parse_mode="HTML",

            reply_markup=kb.as_markup(),
        )


# =========================================================
# SHARE HANDLER
# =========================================================

@router.callback_query(
    F.data.startswith("share_")
)
async def share_handler(
    call: CallbackQuery,
    state: FSMContext,
):

    await call.answer()

    user_id = call.from_user.id

    async with user_lock(user_id):

        share = (
            call.data == "share_yes"
        )

        await state.update_data(
            share_media=share
        )

        await state.set_state(
            UploadState.wait_title
        )

        await call.message.edit_text(

            "📝 <b>MASUKKAN JUDUL FILE</b>\n\n"

            "Kirim judul file.\n"

            "Ketik <code>/skip</code> "
            "untuk menggunakan judul otomatis.",

            parse_mode="HTML",
        )


# =========================================================
# INPUT TITLE
# =========================================================

@router.message(
    UploadState.wait_title
)
async def input_title(
    message: Message,
    state: FSMContext,
):

    user_id = message.from_user.id

    async with user_lock(user_id):

        title = (
            message.text or ""
        ).strip()

        # -------------------------------------------------
        # SKIP
        # -------------------------------------------------

        if title.lower() == "/skip":

            title = "Untitled"

        else:

            if len(title) < 3:

                return await message.answer(
                    "❌ Judul minimal 3 karakter."
                )

            if len(title) > 150:

                return await message.answer(
                    "❌ Judul maksimal 150 karakter."
                )

            if is_bad(title):

                return await message.answer(
                    "❌ Judul tidak diperbolehkan."
                )

        # -------------------------------------------------
        # SAVE TITLE
        # -------------------------------------------------

        await state.update_data(
            title=title
        )

        # -------------------------------------------------
        # FILE TYPE
        # -------------------------------------------------

        kb = InlineKeyboardBuilder()

        kb.button(
            text="🆓 FREE",
            callback_data="file_free",
        )

        kb.button(
            text="💰 PAID",
            callback_data="file_paid",
        )

        kb.adjust(2)

        await message.answer(

            "💎 <b>PILIH TIPE FILE</b>\n\n"

            "🆓 <b>FREE</b>\n"
            "File dapat diakses gratis.\n\n"

            "💰 <b>PAID</b>\n"
            "File harus dibayar terlebih dahulu.\n\n"

            "🔒 PAID hanya tersedia untuk "
            "Kreator terverifikasi.",

            parse_mode="HTML",

            reply_markup=kb.as_markup(),
        )


# =========================================================
# FREE FILE
# =========================================================

@router.callback_query(
    F.data == "file_free"
)
async def file_free(
    call: CallbackQuery,
    state: FSMContext,
):

    await call.answer()

    user_id = call.from_user.id

    async with user_lock(user_id):

        data = await state.get_data()

        if not data.get("media"):

            return await call.answer(
                "❌ Tidak ada media.",
                show_alert=True,
            )

        await state.update_data(

            is_paid=False,

            price=0,

            payment_provider=None,

            review_photos=[],

            saving_msg_id=call.message.message_id,
        )

        try:

            await call.message.edit_text(
                "⏳ <b>Menyimpan file...</b>",
                parse_mode="HTML",
            )

        except Exception:
            pass

        await finalize_save(
            message=call.message,
            state=state,
            user_id=user_id,
        )


# =========================================================
# PAID FILE
# =========================================================

@router.callback_query(
    F.data == "file_paid"
)
async def file_paid(
    call: CallbackQuery,
    state: FSMContext,
):

    data = await state.get_data()

    is_creator = bool(
        data.get(
            "is_creator",
            False
        )
    )

    if not is_creator:

        return await call.answer(
            "🔒 Fitur PAID hanya tersedia "
            "untuk Kreator terverifikasi.",
            show_alert=True,
        )

    await call.answer()

    await state.set_state(
        UploadState.wait_price
    )

    await call.message.edit_text(

        "💰 <b>MASUKKAN HARGA FILE</b>\n\n"

        "Minimal : <b>Rp1.000</b>\n\n"

        "🎨 Status : "
        "<b>Kreator Terverifikasi</b> ✅\n\n"

        "Contoh:\n"
        "<code>1000</code>\n"
        "<code>5000</code>\n"
        "<code>10000</code>",

        parse_mode="HTML",
    )


# =========================================================
# INPUT PRICE
# =========================================================

@router.message(
    UploadState.wait_price
)
async def input_price(
    message: Message,
    state: FSMContext,
):

    user_id = message.from_user.id

    async with user_lock(user_id):

        data = await state.get_data()

        if not data.get(
            "is_creator",
            False
        ):

            await state.set_state(
                UploadState.wait_title
            )

            return await message.answer(
                "🔒 <b>PAID TERKUNCI</b>\n\n"
                "Hanya Kreator terverifikasi "
                "yang dapat membuat file PAID.",
                parse_mode="HTML",
            )

        # -------------------------------------------------
        # NORMALIZE PRICE
        # -------------------------------------------------

        raw = (
            message.text or ""
        ).strip()

        raw = (
            raw
            .replace(".", "")
            .replace(",", "")
            .replace(" ", "")
        )

        if not raw.isdigit():

            return await message.answer(
                "❌ Harga harus berupa angka.\n\n"

                "Contoh:\n"
                "<code>1000</code>\n"
                "<code>5000</code>\n"
                "<code>10000</code>",

                parse_mode="HTML",
            )

        price = int(raw)

        if price < 1000:

            return await message.answer(
                "❌ Harga minimal <b>Rp1.000</b>.",
                parse_mode="HTML",
            )

        # -------------------------------------------------
        # SAVE PAID DATA
        # -------------------------------------------------

        await state.update_data(

            is_paid=True,

            price=price,

            payment_provider="bayargg",

            review_photos=[],
        )

        await state.set_state(
            UploadState.wait_review
        )

        await message.answer(

            "💰 <b>HARGA FILE</b>\n\n"

            f"Harga : <b>{rupiah(price)}</b>\n\n"

            "🖼 <b>UPLOAD REVIEW FILE</b>\n\n"

            "File PAID wajib mempunyai "
            "foto review.\n\n"

            "📸 Minimal : <b>1 foto</b>\n"
            "📸 Maksimal : <b>5 foto</b>\n\n"

            "Contoh review:\n"
            "• Screenshot isi file\n"
            "• Preview produk\n"
            "• Contoh hasil\n"
            "• Screenshot materi\n\n"

            "Kirim foto review sekarang.\n\n"

            "Setelah selesai tekan:\n"
            "✅ <b>SELESAI REVIEW</b>",

            parse_mode="HTML",

            reply_markup=review_keyboard(),
        )


# =========================================================
# RECEIVE REVIEW PHOTO
# =========================================================

@router.message(
    UploadState.wait_review,
    F.photo,
)
async def receive_review_photo(
    message: Message,
    state: FSMContext,
):

    user_id = message.from_user.id

    async with user_lock(user_id):

        data = await state.get_data()

        # Ambil review yang sudah tersimpan
        reviews = data.get("review_photos") or []

        # Pastikan list
        reviews = list(reviews)

        # -------------------------------------------------
        # MAX REVIEW
        # -------------------------------------------------

        if len(reviews) >= MAX_REVIEW_PHOTOS:

            try:
                await message.delete()
            except Exception:
                pass

            return await message.answer(
                f"❌ Maksimal {MAX_REVIEW_PHOTOS} foto review."
            )

        # -------------------------------------------------
        # GET FILE ID
        # -------------------------------------------------

        photo = message.photo[-1]
        file_id = photo.file_id

        # -------------------------------------------------
        # DUPLICATE
        # -------------------------------------------------

        if file_id in reviews:

            try:
                await message.delete()
            except Exception:
                pass

            return await message.answer(
                "⚠️ Foto review tersebut sudah ditambahkan."
            )

        # -------------------------------------------------
        # APPEND
        # -------------------------------------------------

        reviews.append(file_id)

        # -------------------------------------------------
        # SIMPAN STATE
        # -------------------------------------------------

        await state.update_data(
            review_photos=reviews
        )

        # DEBUG
        logger.info(
            "REVIEW PHOTO SAVED | user=%s | total=%s | photos=%s",
            user_id,
            len(reviews),
            reviews,
        )

        # -------------------------------------------------
        # CONFIRM
        # -------------------------------------------------

        await message.answer(

            "🖼 <b>REVIEW DITAMBAHKAN</b>\n\n"

            f"Foto : "
            f"<b>{len(reviews)}/{MAX_REVIEW_PHOTOS}</b>\n\n"

            "Kirim foto review lagi atau tekan:\n"
            "✅ <b>SELESAI REVIEW</b>",

            parse_mode="HTML",

            reply_markup=review_keyboard(),
        )

        # -------------------------------------------------
        # DELETE USER PHOTO
        # -------------------------------------------------

        try:
            await message.delete()
        except Exception:
            pass


# =========================================================
# FINISH REVIEW
# =========================================================

@router.callback_query(
    F.data == "finish_review"
)
async def finish_review(
    call: CallbackQuery,
    state: FSMContext,
):

    user_id = call.from_user.id

    async with user_lock(user_id):

        # -------------------------------------------------
        # GET CURRENT STATE
        # -------------------------------------------------

        current_state = await state.get_state()

        logger.info(
            "FINISH REVIEW | user=%s | state=%s",
            user_id,
            current_state,
        )

        # -------------------------------------------------
        # CHECK STATE
        # -------------------------------------------------

        if current_state != UploadState.wait_review.state:

            return await call.answer(
                "❌ Sesi review sudah berakhir.",
                show_alert=True,
            )

        # -------------------------------------------------
        # GET DATA
        # -------------------------------------------------

        data = await state.get_data()

        reviews = data.get("review_photos") or []

        reviews = list(reviews)

        logger.info(
            "FINISH REVIEW DATA | user=%s | reviews=%s | total=%s",
            user_id,
            reviews,
            len(reviews),
        )

        # -------------------------------------------------
        # VALIDATE
        # -------------------------------------------------

        if len(reviews) < 1:

            return await call.answer(
                "❌ Minimal 1 foto review.",
                show_alert=True,
            )

        if len(reviews) > MAX_REVIEW_PHOTOS:

            return await call.answer(
                f"❌ Maksimal {MAX_REVIEW_PHOTOS} foto review.",
                show_alert=True,
            )

        # -------------------------------------------------
        # ANSWER CALLBACK
        # -------------------------------------------------

        await call.answer()

        # -------------------------------------------------
        # SAVING MESSAGE
        # -------------------------------------------------

        try:

            await call.message.edit_text(

                "⏳ <b>MENYIMPAN FILE...</b>\n\n"

                f"🖼 Review : "
                f"<b>{len(reviews)} foto</b>\n\n"

                "Mohon tunggu...",

                parse_mode="HTML",
            )

        except Exception:
            pass

        await state.update_data(
            saving_msg_id=call.message.message_id
        )

        # -------------------------------------------------
        # FINAL SAVE
        # -------------------------------------------------

        await finalize_save(

            message=call.message,

            state=state,

            user_id=user_id,
        )


# =========================================================
# SEND PAID REVIEW TO CHANNEL
# =========================================================

async def send_paid_review(
    bot,
    *,
    user_id: int,
    username: Optional[str],
    title: str,
    code: str,
    price: int,
    media_count: int,
    review_photos: list,
):
    if not review_photos:
        return

    # -----------------------------------------------------
    # BOT INFO
    # -----------------------------------------------------

    me = await bot.get_me()

    bot_username = me.username or "Unknown"

    # -----------------------------------------------------
    # CAPTION
    # Username creator intentionally omitted from the public
    # review channel for privacy. The marketplace still keeps
    # the owner internally for sales and moderation.
    # -----------------------------------------------------

    caption = (
        "💰 <b>PAID FILE</b>\n"
        f"🤖 Bot : @{bot_username}\n"
        f"📝 Judul : {title}\n"
        f"📦 Total Media : {media_count}\n"
        f"💵 Harga : <b>{rupiah(price)}</b>\n"
        f"🔑 CODE : <code>{code}</code>\n"
        "🛒 File tersedia untuk dibeli."
    )

    # -----------------------------------------------------
    # BUILD ALBUM
    # -----------------------------------------------------

    from aiogram.types import InputMediaPhoto

    media_group = []

    for index, photo_id in enumerate(review_photos):

        if index == 0:
            media_group.append(
                InputMediaPhoto(
                    media=photo_id,
                    caption=caption,
                    parse_mode="HTML",
                )
            )
        else:
            media_group.append(
                InputMediaPhoto(
                    media=photo_id,
                )
            )

    # -----------------------------------------------------
    # SEND ALBUM
    # -----------------------------------------------------

    try:

        await bot.send_media_group(
            chat_id=REVIEW_CHANNEL_ID,
            media=media_group,
        )

        logger.info(
            "PAID REVIEW SENT | code=%s | photos=%s",
            code,
            len(review_photos),
        )

    except TelegramRetryAfter as e:

        logger.warning(
            "TelegramRetryAfter REVIEW | retry=%s",
            e.retry_after,
        )

        await asyncio.sleep(
            e.retry_after + 1
        )

        await bot.send_media_group(
            chat_id=REVIEW_CHANNEL_ID,
            media=media_group,
        )

    except Exception:

        logger.exception(
            "PAID REVIEW ERROR | code=%s",
            code,
        )

        raise


# =========================================================
# SEND UPLOAD LOG
# =========================================================

async def send_upload_log(
    bot,
    *,
    user_id: int,
    title: str,
    code: str,
    media_count: int,
    is_paid: bool,
    price: int,
):

    try:

        me = await bot.get_me()

        bot_username = (
            me.username
            or "Unknown"
        )

        mode = (
            f"💰 PAID {rupiah(price)}"
            if is_paid
            else "🆓 FREE"
        )

        await bot.send_message(

            chat_id=CHANNEL_ID,

            text=(

                "📤 <b>UPLOAD BARU</b>\n\n"

                f"🤖 Bot : @{bot_username}\n"

                f"🆔 ID : "
                f"<code>{mask_user_id(user_id)}</code>\n"

                f"📝 Judul : {title}\n"

                f"📦 Total : "
                f"{media_count} Media\n"

                f"💎 Status : {mode}\n"

                f"🔑 Code : "
                f"<code>{code}</code>"
            ),

            parse_mode="HTML",
        )

    except Exception:

        logger.exception(
            "UPLOAD LOG ERROR | code=%s",
            code,
        )


# =========================================================
# FINAL SAVE
# =========================================================

async def finalize_save(
    message: Message,
    state: FSMContext,
    user_id: int,
):

    data = await state.get_data()

    # -----------------------------------------------------
    # PREVENT DOUBLE SAVE
    # -----------------------------------------------------

    if data.get("saving"):

        return

    await state.update_data(
        saving=True
    )

    try:

        # =================================================
        # MEDIA
        # =================================================

        media = [

            item

            for item in data.get(
                "media",
                []
            )

            if item.get("file_id")
        ]

        if not media:

            await state.update_data(
                saving=False
            )

            return await message.answer(
                "❌ Tidak ada media."
            )

        # =================================================
        # BASIC DATA
        # =================================================

        title = (
            data.get("title")
            or "Untitled"
        )

        share_media = bool(
            data.get(
                "share_media",
                True
            )
        )

        is_paid = bool(
            data.get(
                "is_paid",
                False
            )
        )

        price = int(
            data.get(
                "price",
                0
            )
            or 0
        )

        payment_provider = (
            data.get(
                "payment_provider"
            )
        )

        review_photos = list(
            data.get(
                "review_photos",
                []
            )
        )

        # =================================================
        # PAID VALIDATION
        # =================================================

        if is_paid:

            if not data.get(
                "is_creator",
                False
            ):

                await state.update_data(
                    saving=False
                )

                return await message.answer(
                    "❌ Hanya Kreator "
                    "terverifikasi yang dapat "
                    "membuat file PAID."
                )

            if price < 1000:

                await state.update_data(
                    saving=False
                )

                return await message.answer(
                    "❌ Harga PAID minimal Rp1.000."
                )

            if not review_photos:

                await state.update_data(
                    saving=False
                )

                await state.set_state(
                    UploadState.wait_review
                )

                return await message.answer(
                    "❌ File PAID wajib "
                    "memiliki minimal 1 foto review."
                )

        else:

            price = 0
            payment_provider = None
            review_photos = []

        # =================================================
        # USER DATA
        # =================================================

        username = data.get(
            "creator_username"
        )

        fullname = (
            data.get(
                "creator_fullname"
            )
            or "Unknown"
        )

        # =================================================
        # GENERATE CODE
        # =================================================

        code = await generate_code()

        media_count = len(media)

        media_json = json.dumps(
            media,
            ensure_ascii=False,
        )

        review_json = json.dumps(
            review_photos,
            ensure_ascii=False,
        )

        # =================================================
        # SAVE MEDIA VALUES
        # =================================================

        media_values = []

        for item in media:

            media_values.append((

                code,

                item.get(
                    "message_id"
                ),

                item.get(
                    "file_id"
                ),

                item.get(
                    "type"
                ),

                item.get(
                    "file_size",
                    0
                ),

                title,

                item.get(
                    "position",
                    0
                ),
            ))

        # =================================================
        # DATABASE
        # =================================================

        pool = await get_pool()

        async with pool.acquire() as conn:

            async with conn.transaction():

                # =========================================
                # USER
                # =========================================

                await conn.execute(

                    """
                    INSERT INTO users (
                        user_id,
                        username,
                        fullname
                    )
                    VALUES (
                        $1,
                        $2,
                        $3
                    )
                    ON CONFLICT (user_id)
                    DO UPDATE SET
                        username = EXCLUDED.username,
                        fullname = EXCLUDED.fullname
                    """,

                    user_id,
                    username,
                    fullname,
                )

                # =========================================
                # FILE
                # =========================================

                await conn.execute(

                    """
                    INSERT INTO files (
                        code,
                        title,
                        creator,
                        media,
                        share_media,
                        is_share,
                        owner_id,
                        seller_id,
                        media_count,
                        expires_at,
                        is_paid,
                        price,
                        payment_provider,
                        review_photos,
                        view_count,
                        download_count,
                        favorite_count
                    )
                    VALUES (
                        $1,
                        $2,
                        $3,
                        $4,
                        $5,
                        $6,
                        $7,
                        $8,
                        $9,
                        NULL,
                        $10,
                        $11,
                        $12,
                        $13,
                        0,
                        0,
                        0
                    )
                    """,

                    code,
                    title,
                    fullname,
                    media_json,
                    share_media,
                    share_media,
                    user_id,
                    user_id,
                    media_count,
                    is_paid,
                    price,
                    payment_provider,
                    review_json,
                )

                # =========================================
                # MEDIA TABLE
                # =========================================

                if media_values:

                    await conn.executemany(

                        """
                        INSERT INTO medias (
                            code,
                            message_id,
                            file_id,
                            file_type,
                            file_size,
                            title,
                            position
                        )
                        VALUES (
                            $1,
                            $2,
                            $3,
                            $4,
                            $5,
                            $6,
                            $7
                        )
                        """,

                        media_values,
                    )

        # =================================================
        # DATABASE SUCCESS
        # =================================================

        logger.info(
            "FILE SAVED | "
            "user=%s | code=%s | "
            "media=%s | paid=%s",
            user_id,
            code,
            media_count,
            is_paid,
        )

        # =================================================
        # DELETE OLD PROGRESS MESSAGE
        # =================================================

        progress_id = data.get(
            "progress_msg_id"
        )

        saving_msg_id = data.get(
            "saving_msg_id"
        )

        for message_id in (
            progress_id,
            saving_msg_id,
        ):

            if not message_id:
                continue

            try:

                await message.bot.delete_message(

                    chat_id=message.chat.id,

                    message_id=message_id,
                )

            except Exception:
                pass

        # =================================================
        # CLEAR STATE
        # =================================================

        await state.clear()

        # =================================================
        # MEDIA SUMMARY
        # =================================================

        video_count = sum(
            1
            for item in media
            if item.get("type") == "video"
        )

        photo_count = sum(
            1
            for item in media
            if item.get("type") == "photo"
        )

        document_count = sum(
            1
            for item in media
            if item.get("type") == "document"
        )

        info = []

        if video_count:
            info.append(
                f"{video_count} Video"
            )

        if photo_count:
            info.append(
                f"{photo_count} Photo"
            )

        if document_count:
            info.append(
                f"{document_count} Document"
            )

        files_info = (
            " • ".join(info)
            if info
            else "0 File"
        )

        # =================================================
        # STATUS
        # =================================================

        if is_paid:

            mode = (
                f"💰 PAID "
                f"{rupiah(price)}"
            )

        else:

            mode = "🆓 FREE"

        # =================================================
        # SUCCESS MESSAGE
        # =================================================

        await message.answer(

            (
                "✅ <b>FILE BERHASIL DISIMPAN</b>\n\n"

                f"📝 <b>Judul</b> : "
                f"{title}\n"

                f"📦 <b>Total Media</b> : "
                f"{media_count}\n"

                f"📁 <b>Isi</b> : "
                f"{files_info}\n"

                f"💎 <b>Status</b> : "
                f"{mode}\n\n"

                f"🔑 <b>Code</b> : "
                f"<code>{code}</code>"
            ),

            parse_mode="HTML",
        )

        # =================================================
        # SEND PAID REVIEW
        # =================================================

        if is_paid and review_photos:

            try:

                await send_paid_review(

                    message.bot,

                    user_id=user_id,

                    username=username,

                    title=title,

                    code=code,

                    price=price,

                    media_count=media_count,

                    review_photos=review_photos,
                )

            except Exception:

                # Review gagal tidak membatalkan file.
                logger.exception(
                    "PAID REVIEW ERROR | code=%s",
                    code,
                )

        # =================================================
        # SEND UPLOAD LOG
        # =================================================

        await send_upload_log(

            message.bot,

            user_id=user_id,

            title=title,

            code=code,

            media_count=media_count,

            is_paid=is_paid,

            price=price,
        )

    # =====================================================
    # FINAL ERROR
    # =====================================================

    except Exception:

        logger.exception(
            "FINAL SAVE ERROR | user=%s",
            user_id,
        )

        await state.update_data(
            saving=False
        )

        try:

            await message.answer(

                "❌ <b>GAGAL MENYIMPAN FILE</b>\n\n"

                "Terjadi kesalahan saat "
                "menyimpan file ke database.\n\n"

                "Silakan coba lagi.",

                parse_mode="HTML",
            )

        except Exception:

            logger.exception(
                "ERROR MESSAGE FAILED"
            )
