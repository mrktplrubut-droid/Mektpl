import re

from aiogram import Router, F
from aiogram.types import (
    Message,
    InlineKeyboardMarkup,
    InlineKeyboardButton
)
from aiogram.fsm.context import FSMContext

from database import get_pool


router = Router()


# =====================================
# REGEX CODE
# =====================================

CODE_REGEX = re.compile(
    r"[a-z0-9]{30,60}",
    re.IGNORECASE
)


def normalize_code(code: str):

    return (
        code
        .strip()
        .replace(" ", "")
        .replace("\n", "")
        .lower()
    )



# =====================================
# KEYBOARD
# =====================================

def kb_open():

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📥 Buka File",
                    callback_data="getfile"
                )
            ]
        ]
    )


def kb_upload():

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📤 Upload File",
                    callback_data="upfile"
                )
            ]
        ]
    )

def kb_channel():

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📢 Channel",
                    callback_data="channel"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🏠 Menu Utama",
                    callback_data="home"
                )
            ]
        ]
    )



def kb_home():

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="START",
                    callback_data="home"
                )
            ]
        ]
    )



# =====================================
# TEXT NOTIFY
# =====================================

@router.message(
    F.text
)
async def notify_text(
    message: Message,
    state: FSMContext
):


    # jangan ganggu upload/payment FSM
    if await state.get_state():
        return



    text = message.text.strip()


    # =========================
    # IGNORE COMMAND
    # =========================

    if text.startswith("/"):
        return



    lower = text.lower()



    # =========================
    # CHANNEL KEYWORD
    # =========================

    keywords = {
        "group",
        "grup",
        "channel",
        "ch",
        "info",
        "bokep",
        "bocil",
        "indo",
        "ngewe"
    }


    if lower in keywords:

        return await message.answer(
            (
                "📢 <b>MENU CHANNEL</b>\n\n"
                "Silakan buka daftar channel informasi."
            ),
            parse_mode="HTML",
            reply_markup=kb_channel()
        )



    # =========================
    # CODE DETECT
    # =========================

    match = CODE_REGEX.search(text)


    if match:


        code = normalize_code(
            match.group(0)
        )


        pool = await get_pool()


        exists = await pool.fetchval(
            """
            SELECT EXISTS(
                SELECT 1
                FROM files
                WHERE LOWER(TRIM(code))=$1
            )
            """,
            code
        )



        if exists:

            return await message.answer(
                (
                    "🔑 <b>CODE TERDETEKSI</b>\n\n"
                    "Kode file valid ditemukan.\n\n"
                    "Tekan tombol untuk membuka file."
                ),
                parse_mode="HTML",
                reply_markup=kb_open()
            )



        return await message.answer(
            (
                "❌ <b>CODE TIDAK VALID</b>\n\n"
                "Kode tidak ditemukan."
            ),
            parse_mode="HTML",
            reply_markup=kb_home()
        )



    # =========================
    # DEFAULT TEXT
    # =========================

    return await message.answer(
        (
            "👋 <b>Halo!</b>\n\n"
            "Silakan tekan tombol <b>START</b> untuk membuka menu bot."
        ),
        parse_mode="HTML",
        reply_markup=kb_home()
    )



# =====================================
# MEDIA NOTIFY
# =====================================

@router.message(
    F.photo
    | F.video
    | F.document
    | F.audio
    | F.voice
    | F.animation
    | F.sticker
)
async def notify_media(
    message: Message,
    state: FSMContext
):


    # jangan ganggu upload aktif
    if await state.get_state():
        return



    return await message.answer(
        (
            "📤 <b>MEDIA TERDETEKSI</b>\n\n"
            "Media ditemukan.\n\n"
            "Tekan Upload File untuk menyimpan ke bot."
        ),
        parse_mode="HTML",
        reply_markup=kb_upload()
    )



# =====================================
# FALLBACK
# =====================================

@router.message()
async def notify_other(
    message: Message,
    state: FSMContext
):


    if await state.get_state():
        return


    return await message.answer(
        (
            "🤖 <b>BOT MARKET</b>\n\n"
            "Gunakan menu yang tersedia."
        ),
        parse_mode="HTML",
        reply_markup=kb_home()
    )
