import asyncio
import json
import logging
import re
import time

from typing import Dict
from contextlib import asynccontextmanager

from aiogram.filters import StateFilter
from aiogram import Router, F
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)

from database import get_pool
from utils.user import get_user_status


router = Router()

logger = logging.getLogger(__name__)


# ============================================================
# CONFIG
# ============================================================

UPDATE_DELAY = 0.5

CODE_MIN_LENGTH = 30
CODE_MAX_LENGTH = 60


# ============================================================
# USER LOCK
# ============================================================

_last_update: Dict[int, float] = {}
_user_locks: Dict[int, asyncio.Lock] = {}


def get_lock(user_id: int) -> asyncio.Lock:
    """
    Satu user tidak boleh menjalankan beberapa proses Get File
    secara bersamaan.
    """

    user_id = int(user_id)

    if user_id not in _user_locks:
        _user_locks[user_id] = asyncio.Lock()

    return _user_locks[user_id]


@asynccontextmanager
async def user_lock(user_id: int):
    async with get_lock(user_id):
        yield


# ============================================================
# FSM
# ============================================================

class GetFileState(StatesGroup):
    waiting_code = State()


# ============================================================
# CALLBACK SAFE ANSWER
# ============================================================

async def safe_callback_answer(
    call: CallbackQuery,
    text: str | None = None,
    show_alert: bool = False,
):
    """
    Menjawab callback Telegram dengan aman.

    CallbackQuery mempunyai batas waktu. Kalau handler terlalu
    lama dan callback sudah expired, Telegram mengembalikan:

    TelegramBadRequest:
    query is too old and response timeout expired

    Error ini tidak boleh membuat bot crash.
    """

    try:
        await call.answer(
            text=text,
            show_alert=show_alert,
        )

    except TelegramBadRequest as exc:

        error_text = str(exc).lower()

        if (
            "query is too old" in error_text
            or "response timeout expired" in error_text
            or "query id is invalid" in error_text
        ):
            logger.warning(
                "CALLBACK EXPIRED | user=%s | data=%s",
                getattr(call.from_user, "id", None),
                getattr(call, "data", None),
            )
            return False

        logger.warning(
            "CALLBACK ANSWER BAD REQUEST | %s",
            exc,
        )
        return False

    except Exception:
        logger.exception(
            "CALLBACK ANSWER ERROR"
        )
        return False

    return True


# ============================================================
# JSON
# ============================================================

def safe_json(data):
    """
    Mengubah media JSON menjadi object Python.
    """

    if isinstance(data, str):

        try:
            return json.loads(data)

        except (json.JSONDecodeError, TypeError, ValueError):
            logger.warning(
                "INVALID MEDIA JSON"
            )
            return []

        except Exception:
            logger.exception(
                "MEDIA JSON PARSE ERROR"
            )
            return []

    return data or []


# ============================================================
# CODE NORMALIZER
# ============================================================

CODE_REGEX = re.compile(
    rf"\b[a-z0-9]{{{CODE_MIN_LENGTH},{CODE_MAX_LENGTH}}}\b",
    re.IGNORECASE,
)


def normalize_code(code: str) -> str:
    """
    Normalisasi code agar pencarian konsisten.
    """

    if not code:
        return ""

    return (
        str(code)
        .strip()
        .replace(" ", "")
        .replace("\n", "")
        .replace("\r", "")
        .lower()
    )


# ============================================================
# SAFE MESSAGE UPDATE
# ============================================================

async def safe_update(
    bot,
    chat_id: int,
    message_id: int,
    text: str,
    reply_markup=None,
):
    """
    Edit message dengan rate limit sederhana.
    """

    now = time.time()

    previous = _last_update.get(chat_id)

    if (
        previous is not None
        and now - previous < UPDATE_DELAY
    ):
        return False

    _last_update[chat_id] = now

    try:
        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=text,
            parse_mode="HTML",
            reply_markup=reply_markup,
        )

        return True

    except TelegramBadRequest as exc:

        # Message tidak berubah / message sudah tidak ada
        # tidak boleh membuat bot crash.
        logger.debug(
            "GETFILE MESSAGE UPDATE IGNORED | %s",
            exc,
        )

        return False

    except Exception:
        logger.exception(
            "GETFILE UPDATE ERROR"
        )

        return False


# ============================================================
# BUTTON GET FILE
# ============================================================

@router.callback_query(
    F.data == "getfile"
)
async def getfile_start(
    call: CallbackQuery,
    state: FSMContext,
):
    """
    Membuka mode Get File.

    PENTING:
    Callback langsung di-answer sebelum database/FSM/message
    processing supaya tidak terkena timeout Telegram.
    """

    # ========================================================
    # ACK CALLBACK SECEPAT MUNGKIN
    # ========================================================

    await safe_callback_answer(call)

    user_id = int(call.from_user.id)

    async with user_lock(user_id):

        # ====================================================
        # FSM
        # ====================================================

        await state.clear()

        await state.set_state(
            GetFileState.waiting_code
        )

        # ====================================================
        # TEXT
        # ====================================================

        text = (
            "📥 <b>GET FILE MODE</b>\n\n"
            "Silakan kirim <b>CODE</b> file sekarang."
        )

        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="🏠 Home",
                        callback_data="home",
                    )
                ]
            ]
        )

        # ====================================================
        # MESSAGE
        # ====================================================

        progress_id = None

        try:

            await call.message.edit_text(
                text=text,
                parse_mode="HTML",
                reply_markup=keyboard,
            )

            progress_id = call.message.message_id

        except TelegramBadRequest:

            try:

                msg = await call.message.answer(
                    text=text,
                    parse_mode="HTML",
                    reply_markup=keyboard,
                )

                progress_id = msg.message_id

            except Exception:
                logger.exception(
                    "GETFILE START SEND MESSAGE ERROR"
                )

        except Exception:
            logger.exception(
                "GETFILE START EDIT ERROR"
            )

        # ====================================================
        # SAVE FSM DATA
        # ====================================================

        if progress_id:

            await state.update_data(
                getfile_mode=True,
                progress_msg_id=progress_id,
            )


# ============================================================
# OPEN FILE
# ============================================================

async def open_file_by_code(
    message: Message,
    code: str,
    state: FSMContext,
):
    """
    Membuka file berdasarkan code.
    """

    code = normalize_code(code)

    if not code:
        await state.clear()

        return await message.answer(
            "❌ CODE tidak valid."
        )

    pool = await get_pool()

    # ========================================================
    # DATABASE FILE
    # ========================================================

    file = await pool.fetchrow(
        """
        SELECT
            code,
            title,
            media,
            owner_id,
            expires_at,
            is_paid,
            price,
            views
        FROM files
        WHERE LOWER(TRIM(code)) = LOWER(TRIM($1))
        LIMIT 1
        """,
        code,
    )

    # ========================================================
    # FILE TIDAK DITEMUKAN
    # ========================================================

    if not file:

        await state.clear()

        return await message.answer(
            "❌ File tidak ditemukan."
        )

    # ========================================================
    # MEDIA
    # ========================================================

    media = safe_json(
        file["media"]
    )

    if not isinstance(media, list) or not media:

        await state.clear()

        return await message.answer(
            "❌ File kosong."
        )

    # ========================================================
    # EXPIRED
    # ========================================================

    expires_at = file["expires_at"]

    if expires_at:

        try:

            if expires_at.timestamp() < time.time():

                await state.clear()

                return await message.answer(
                    "❌ File sudah kadaluarsa."
                )

        except Exception:
            logger.warning(
                "INVALID EXPIRES_AT | code=%s",
                code,
                exc_info=True,
            )

    # ========================================================
    # OWNER
    # ========================================================

    owner_id = file["owner_id"]

    owner = False

    try:

        owner = (
            int(message.from_user.id)
            == int(owner_id)
        )

    except (ValueError, TypeError):

        owner = False

    # ========================================================
    # PAYMENT
    # ========================================================

    is_paid = bool(
        file["is_paid"]
    )

    price = file["price"] or 0

    try:
        price = int(price)

    except (ValueError, TypeError):
        price = 0

    # ========================================================
    # USER STATUS
    # ========================================================

    try:

        user_level = await get_user_status(
            pool,
            message.from_user.id,
        )

    except Exception:

        logger.exception(
            "GET USER STATUS ERROR | user=%s",
            message.from_user.id,
        )

        user_level = None

    # ========================================================
    # CREATOR ACCESS
    # ========================================================

    creator_access = False

    try:

        creator_access = await pool.fetchval(
            """
            SELECT
                COALESCE(is_creator, FALSE)
                AND COALESCE(
                    creator_status,
                    'none'
                ) = 'approved'
            FROM users
            WHERE chat_id = $1
            LIMIT 1
            """,
            message.from_user.id,
        ) or False

    except Exception:

        logger.exception(
            "CREATOR ACCESS CHECK ERROR | user=%s",
            message.from_user.id,
        )

        creator_access = False

    # ========================================================
    # PURCHASE
    # ========================================================

    access = False

    try:

        access = await pool.fetchval(
            """
            SELECT EXISTS(
                SELECT 1
                FROM file_purchases
                WHERE user_id = $1
                  AND LOWER(TRIM(file_code))
                      = LOWER(TRIM($2))
                  AND status = 'paid'
            )
            """,
            message.from_user.id,
            code,
        )

    except Exception:

        logger.exception(
            "PURCHASE ACCESS CHECK ERROR | "
            "user=%s | code=%s",
            message.from_user.id,
            code,
        )

        access = False

    # ========================================================
    # FINAL ACCESS
    # ========================================================

    has_access = (
        owner
        or bool(access)
        or bool(creator_access)
        or user_level in (
            "vip",
            "vvip",
        )
    )

    # ========================================================
    # VIEW COUNT
    # ========================================================

    if not is_paid or has_access:

        try:

            viewed = await pool.fetchrow(
                """
                INSERT INTO file_views
                (
                    user_id,
                    file_code
                )
                VALUES
                (
                    $1,
                    $2
                )
                ON CONFLICT
                (
                    user_id,
                    file_code
                )
                DO NOTHING
                RETURNING user_id
                """,
                message.from_user.id,
                file["code"],
            )

            if viewed:

                await pool.execute(
                    """
                    UPDATE files
                    SET
                        views =
                            COALESCE(views, 0) + 1,
                        view_count =
                            COALESCE(view_count, 0) + 1
                    WHERE code = $1
                    """,
                    file["code"],
                )

        except Exception:

            # Statistik gagal tidak boleh membuat
            # user kehilangan akses ke file.
            logger.exception(
                "FILE VIEW UPDATE ERROR | code=%s",
                file["code"],
            )

    # ========================================================
    # CLEAR FSM
    # ========================================================

    await state.clear()

    # ========================================================
    # PAID BUT NO ACCESS
    # ========================================================

    if is_paid and not has_access:

        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=(
                            f"💳 BAYAR Rp "
                            f"{price:,.0f}"
                        ).replace(",", "."),
                        callback_data=f"pay:{code}",
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="🏠 Home",
                        callback_data="home",
                    )
                ],
            ]
        )

        return await message.answer(
            (
                "🔒 <b>FILE BERBAYAR</b>\n\n"
                f"🔑 CODE : "
                f"<code>{code}</code>\n"
                f"💰 Harga : "
                f"Rp {price:,}\n\n"
                "Silakan lakukan pembayaran "
                "untuk membuka file."
            ).replace(",", "."),
            parse_mode="HTML",
            reply_markup=keyboard,
        )

    # ========================================================
    # OPEN FILE
    # ========================================================

    try:

        from handlers.open_menu import open_keyboard

    except Exception:

        logger.exception(
            "OPEN MENU IMPORT ERROR"
        )

        return await message.answer(
            "❌ Menu file sedang mengalami masalah."
        )

    title = str(
        file["title"] or "Tanpa Judul"
    )

    return await message.answer(
        (
            "✅ <b>FILE DITEMUKAN</b>\n\n"
            f"📝 Judul : "
            f"<b>{title}</b>\n"
            f"📦 Total Media : "
            f"<b>{len(media)}</b>\n\n"
            "Pilih metode pengiriman:"
        ),
        parse_mode="HTML",
        reply_markup=open_keyboard(code),
    )


# ============================================================
# PROCESS CODE
# ============================================================

async def process_code(
    message: Message,
    code: str,
):
    """
    Compatibility helper untuk pemanggilan dari handler lain.
    """

    code = normalize_code(code)

    class DummyState:

        async def clear(self):
            return None

        async def get_data(self):
            return {}

        async def update_data(self, **kwargs):
            return None

    return await open_file_by_code(
        message=message,
        code=code,
        state=DummyState(),
    )


# ============================================================
# RECEIVE CODE
# ============================================================

@router.message(
    StateFilter(
        GetFileState.waiting_code
    ),
    F.text,
)
async def receive_code(
    message: Message,
    state: FSMContext,
):
    """
    Menerima code dari user.
    """

    user_id = int(
        message.from_user.id
    )

    async with user_lock(user_id):

        text = (
            message.text or ""
        ).strip()

        match = CODE_REGEX.search(
            text
        )

        # ====================================================
        # INVALID CODE
        # ====================================================

        if not match:

            try:
                await message.delete()

            except Exception:
                pass

            return await message.answer(
                "❌ Itu bukan CODE bot saya.\n\n"
                "Silakan kirim CODE yang benar "
                "atau tekan Cancel."
            )

        # ====================================================
        # NORMALIZE
        # ====================================================

        code = normalize_code(
            match.group()
        )

        # ====================================================
        # DELETE USER MESSAGE
        # ====================================================

        try:

            await message.delete()

        except Exception:
            pass

        # ====================================================
        # DELETE PROGRESS MESSAGE
        # ====================================================

        try:

            data = await state.get_data()

            progress_id = data.get(
                "progress_msg_id"
            )

            if progress_id:

                try:

                    await message.bot.delete_message(
                        chat_id=message.chat.id,
                        message_id=int(
                            progress_id
                        ),
                    )

                except Exception:
                    pass

        except Exception:

            logger.exception(
                "GETFILE PROGRESS DELETE ERROR"
            )

        # ====================================================
        # OPEN
        # ====================================================

        return await open_file_by_code(
            message=message,
            code=code,
            state=state,
        )


# ============================================================
# CANCEL GET FILE
# ============================================================

@router.callback_query(
    F.data == "cancel_getfile"
)
async def cancel_getfile(
    call: CallbackQuery,
    state: FSMContext,
):
    """
    Membatalkan mode Get File.
    """

    # ACK SECEPAT MUNGKIN
    await safe_callback_answer(call)

    user_id = int(
        call.from_user.id
    )

    async with user_lock(user_id):

        await state.clear()

        text = (
            "❌ <b>Get File dibatalkan.</b>"
        )

        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="🏠 Home",
                        callback_data="home",
                    )
                ]
            ]
        )

        try:

            await call.message.edit_text(
                text,
                parse_mode="HTML",
                reply_markup=keyboard,
            )

        except TelegramBadRequest:

            try:

                await call.message.answer(
                    text,
                    parse_mode="HTML",
                    reply_markup=keyboard,
                )

            except Exception:
                logger.exception(
                    "CANCEL GETFILE SEND ERROR"
                )

        except Exception:

            logger.exception(
                "CANCEL GETFILE EDIT ERROR"
            )
