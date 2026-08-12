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


logging.basicConfig(level=logging.INFO)


UPDATE_DELAY = 0.5


_last_update: Dict[int, float] = {}
_user_locks: Dict[int, asyncio.Lock] = {}


def get_lock(user_id:int):

    if user_id not in _user_locks:
        _user_locks[user_id] = asyncio.Lock()

    return _user_locks[user_id]


@asynccontextmanager
async def user_lock(user_id:int):

    async with get_lock(user_id):
        yield



class GetFileState(StatesGroup):

    waiting_code = State()



def safe_json(data):

    if isinstance(data,str):

        try:
            return json.loads(data)

        except:
            return []

    return data or []



async def safe_update(
    bot,
    chat_id:int,
    message_id:int,
    text:str,
    reply_markup=None
):

    now=time.time()

    if chat_id in _last_update:

        if now - _last_update[chat_id] < UPDATE_DELAY:
            return


    _last_update[chat_id]=now


    try:

        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=text,
            parse_mode="HTML",
            reply_markup=reply_markup
        )


    except TelegramBadRequest:
        pass


    except Exception:
        logging.exception("GETFILE UPDATE ERROR")



# =====================================
# BUTTON GET FILE
# =====================================

@router.callback_query(F.data == "getfile")
async def getfile_start(
    call: CallbackQuery,
    state: FSMContext
):
    await call.answer()

    async with user_lock(call.from_user.id):

        await state.clear()
        await state.set_state(GetFileState.waiting_code)

        text = (
            "📥 <b>GET FILE MODE</b>\n\n"
            "Silakan kirim <b>CODE</b> file sekarang."
        )

        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="🏠 Home",
                        callback_data="home"
                    )
                ]
            ]
        )

        try:
            await call.message.edit_text(
                text=text,
                parse_mode="HTML",
                reply_markup=keyboard
            )
            progress_id = call.message.message_id

        except TelegramBadRequest:
            msg = await call.message.answer(
                text=text,
                parse_mode="HTML",
                reply_markup=keyboard
            )
            progress_id = msg.message_id

        await state.update_data(
            getfile_mode=True,
            progress_msg_id=progress_id
        )

# =====================================
# OPEN FILE
# =====================================

async def open_file_by_code(
    message: Message,
    code: str,
    state: FSMContext
):
    pool = await get_pool()

    file = await pool.fetchrow(
        """
        SELECT
            code,
            title,
            media,
            owner_id,
            expires_at,
            is_paid,
            price
        FROM files
        WHERE LOWER(TRIM(code)) = LOWER(TRIM($1))
        LIMIT 1
        """,
        code
    )

    if not file:
        await state.clear()
        return await message.answer(
            "❌ File tidak ditemukan."
        )

    media = safe_json(file["media"])

    if not media:
        await state.clear()
        return await message.answer(
            "❌ File kosong."
        )

    if (
        file["expires_at"]
        and file["expires_at"].timestamp() < time.time()
    ):
        await state.clear()
        return await message.answer(
            "❌ File sudah kadaluarsa."
        )

    owner = (
        message.from_user.id == file["owner_id"]
    )

    is_paid = bool(file["is_paid"])
    price = file["price"] or 0

    user_level = await get_user_status(
        pool,
        message.from_user.id
    )

    access = await pool.fetchval(
        """
        SELECT EXISTS(
            SELECT 1
            FROM file_purchases
            WHERE user_id=$1
              AND file_code=$2
              AND status='paid'
        )
        """,
        message.from_user.id,
        code
    )

    has_access = (
        owner
        or access
        or user_level in ("vip", "vvip")
    )

    await state.clear()

    if is_paid and not has_access:

        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=f"💳 BAYAR Rp {price:,.0f}".replace(",", "."),
                        callback_data=f"pay:{code}"
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="🏠 Home",
                        callback_data="home"
                    )
                ]
            ]
        )

        return await message.answer(
            (
                "🔒 <b>FILE BERBAYAR</b>\n\n"
                f"🔑 CODE : <code>{code}</code>\n"
                f"💰 Harga : Rp {price:,}\n\n"
                "Silakan lakukan pembayaran untuk membuka file."
            ).replace(",", "."),
            parse_mode="HTML",
            reply_markup=keyboard
        )

    from handlers.open_menu import open_keyboard

    return await message.answer(
        (
            "✅ <b>FILE DITEMUKAN</b>\n\n"
            f"📝 Judul : <b>{file['title']}</b>\n"
            f"📦 Total Media : <b>{len(media)}</b>\n\n"
            "Pilih metode pengiriman:"
        ),
        parse_mode="HTML",
        reply_markup=open_keyboard(code)
    )



# =====================================
# RECEIVE CODE
# =====================================

CODE_REGEX = re.compile(
    r"\b[a-z0-9]{30,60}\b",
    re.IGNORECASE
)


def normalize_code(code: str):
    return (
        code.strip()
        .replace(" ", "")
        .replace("\n", "")
        .lower()
    )

async def process_code(
    message: Message,
    code: str
):
    code = normalize_code(code)

    class DummyState:
        async def clear(self):
            pass

    return await open_file_by_code(
        message=message,
        code=code,
        state=DummyState()
    )


@router.message(
    StateFilter(GetFileState.waiting_code),
    F.text
)
async def receive_code(
    message: Message,
    state: FSMContext
):

    async with user_lock(message.from_user.id):

        text = (message.text or "").strip()

        match = CODE_REGEX.search(text)

        if not match:

            try:
                await message.delete()
            except Exception:
                pass

            # JANGAN clear state
            return await message.answer(
                "❌ Itu bukan CODE bot saya.\n\n"
                "Silakan kirim CODE yang benar atau tekan Cancel."
            )

        code = normalize_code(match.group())

        try:
            await message.delete()
        except Exception:
            pass

        data = await state.get_data()

        progress_id = data.get("progress_msg_id")

        if progress_id:
            try:
                await message.bot.delete_message(
                    chat_id=message.chat.id,
                    message_id=progress_id
                )
            except Exception:
                pass

        return await open_file_by_code(
            message=message,
            code=code,
            state=state
        )

# =====================================
# CANCEL GET FILE
# =====================================

@router.callback_query(F.data=="cancel_getfile")
async def cancel_getfile(
    call: CallbackQuery,
    state: FSMContext
):

    await call.answer()


    async with user_lock(call.from_user.id):

        await state.clear()


        try:

            await call.message.edit_text(
                "❌ <b>Get File dibatalkan.</b>",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            InlineKeyboardButton(
                                text="🏠 Home",
                                callback_data="home"
                            )
                        ]
                    ]
                )
            )

        except:

            await call.message.answer(
                "❌ <b>Get File dibatalkan.</b>",
                parse_mode="HTML"
            )
