import asyncio
import re

from aiogram import Router, F
from aiogram.types import (
    Message,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from aiogram.fsm.context import FSMContext

from database import get_pool


router = Router()


# =========================================================
# REGEX CODE
# =========================================================

CODE_REGEX = re.compile(
    r"[a-z0-9]{30,60}",
    re.IGNORECASE,
)


def normalize_code(code: str) -> str:
    return (
        code
        .strip()
        .replace(" ", "")
        .replace("\n", "")
        .lower()
    )


# =========================================================
# LOADING
# =========================================================

async def send_loading(message: Message):
    """
    Kirim pesan loading pencarian.
    """

    try:
        return await message.answer(
            "🔎 <b>Mencari...</b>\n"
            "⏳ Mohon tunggu sebentar...",
            parse_mode="HTML",
        )
    except Exception:
        return None


async def delete_loading(loading_message):
    """
    Hapus pesan loading dengan aman.
    """

    if not loading_message:
        return

    try:
        await loading_message.delete()
    except Exception:
        pass


async def loading_animation(message: Message):
    """
    Loading sederhana.
    """

    try:
        loading = await message.answer(
            "🔎 <b>Mencari</b> ⏳",
            parse_mode="HTML",
        )

        await asyncio.sleep(0.25)

        try:
            await loading.edit_text(
                "🔎 <b>Mencari.</b> ⏳",
                parse_mode="HTML",
            )
        except Exception:
            pass

        await asyncio.sleep(0.25)

        try:
            await loading.edit_text(
                "🔎 <b>Mencari..</b> ⏳",
                parse_mode="HTML",
            )
        except Exception:
            pass

        await asyncio.sleep(0.25)

        try:
            await loading.edit_text(
                "🔎 <b>Mencari...</b> ⏳",
                parse_mode="HTML",
            )
        except Exception:
            pass

        return loading

    except Exception:
        return None


# =========================================================
# KEYBOARD
# =========================================================

def kb_open():

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📥 Buka File",
                    callback_data="getfile",
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
                    callback_data="upfile",
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
                    callback_data="channel",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🏠 Menu Utama",
                    callback_data="home",
                )
            ],
        ]
    )


# =========================================================
# VIP KEYBOARD
# =========================================================

def kb_vip():

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="👑 Buka VIP",
                    callback_data="vip",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🏠 Menu Utama",
                    callback_data="home",
                )
            ],
        ]
    )


# =========================================================
# MARKETPLACE KEYBOARD
# =========================================================

def kb_marketplace():

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🛍 Marketplace",
                    callback_data="marketplace",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🏠 Menu Utama",
                    callback_data="home",
                )
            ],
        ]
    )


# =========================================================
# CREATOR KEYBOARD
# =========================================================

def kb_creator():

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🎨 Buka Kreator",
                    callback_data="creator",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🏠 Menu Utama",
                    callback_data="home",
                )
            ],
        ]
    )


# =========================================================
# HOME
# =========================================================

def kb_home():

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🚀 START",
                    callback_data="home",
                )
            ]
        ]
    )


# =========================================================
# TEXT NOTIFY
# =========================================================

@router.message(F.text)
async def notify_text(
    message: Message,
    state: FSMContext,
):

    # =====================================================
    # JANGAN GANGGU FSM
    # =====================================================

    current_state = await state.get_state()

    if current_state:
        return


    text = message.text.strip()

    if not text:
        return


    # =====================================================
    # COMMAND
    # =====================================================

    if text.startswith("/"):
        return


    lower = text.lower().strip()


    # =====================================================
    # LOADING
    # =====================================================

    loading = await loading_animation(message)


    try:

        # Sedikit delay agar loading benar-benar terlihat
        await asyncio.sleep(0.15)


        # =================================================
        # VIP / VVIP
        # =================================================

        vip_keywords = {
            "vip",
            "vvip",
        }

        if lower in vip_keywords:

            return await message.answer(
                (
                    "👑 <b>VIP / VVIP</b>\n\n"
                    "✨ Konten VIP tersedia di sini.\n\n"
                    "Silakan tekan tombol di bawah "
                    "untuk membuka menu VIP."
                ),
                parse_mode="HTML",
                reply_markup=kb_vip(),
            )


        # =================================================
        # MARKETPLACE
        # =================================================

        marketplace_keywords = {
            "video",
            "viral",
        }

        if lower in marketplace_keywords:

            return await message.answer(
                (
                    "🛍 <b>MARKETPLACE</b>\n\n"
                    "🔥 Code dan media yang tersedia "
                    "dapat kamu temukan di Marketplace.\n\n"
                    "Silakan buka Marketplace untuk "
                    "melihat semua code yang tersedia."
                ),
                parse_mode="HTML",
                reply_markup=kb_marketplace(),
            )


        # =================================================
        # CREATOR
        # =================================================

        creator_keywords = {
            "kreator",
            "creator",
        }

        if lower in creator_keywords:

            return await message.answer(
                (
                    "🎨 <b>PROGRAM KREATOR</b>\n\n"
                    "🚀 Jadilah Kreator dan dapatkan "
                    "penghasilan dari code yang kamu upload.\n\n"
                    "✨ Kamu dapat mengelola code, "
                    "menjualnya melalui Marketplace, "
                    "dan mendapatkan penghasilan dari "
                    "setiap penjualan.\n\n"
                    "Tekan tombol di bawah untuk membuka "
                    "Program Kreator."
                ),
                parse_mode="HTML",
                reply_markup=kb_creator(),
            )


        # =================================================
        # CHANNEL
        # =================================================

        channel_keywords = {
            "group",
            "grup",
            "channel",
            "ch",
            "info",
            "bokep",
            "bocil",
            "indo",
            "ngewe",
        }

        if lower in channel_keywords:

            return await message.answer(
                (
                    "📢 <b>MENU CHANNEL</b>\n\n"
                    "Silakan buka daftar channel "
                    "yang tersedia."
                ),
                parse_mode="HTML",
                reply_markup=kb_channel(),
            )


        # =================================================
        # CODE DETECTION
        # =================================================

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
                    WHERE LOWER(TRIM(code)) = $1
                )
                """,
                code,
            )

            if exists:

                return await message.answer(
                    (
                        "🔑 <b>CODE TERDETEKSI</b>\n\n"
                        "✅ Kode file valid ditemukan.\n\n"
                        "Tekan tombol di bawah "
                        "untuk membuka file."
                    ),
                    parse_mode="HTML",
                    reply_markup=kb_open(),
                )

            return await message.answer(
                (
                    "❌ <b>CODE TIDAK DITEMUKAN</b>\n\n"
                    "Kode yang kamu kirim tidak tersedia "
                    "di database."
                ),
                parse_mode="HTML",
                reply_markup=kb_home(),
            )


        # =================================================
        # DEFAULT TEXT
        # =================================================

        return await message.answer(
            (
                "👋 <b>Halo!</b>\n\n"
                "Saya sedang mencari menu yang sesuai "
                "dengan pesan kamu.\n\n"
                "Gunakan menu <b>START</b> untuk melihat "
                "semua fitur bot."
            ),
            parse_mode="HTML",
            reply_markup=kb_home(),
        )

    finally:

        # =================================================
        # DELETE LOADING
        # =================================================

        await delete_loading(loading)


# =========================================================
# MEDIA NOTIFY
# =========================================================

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
    state: FSMContext,
):

    # =====================================================
    # JANGAN GANGGU UPLOAD / PAYMENT / FSM
    # =====================================================

    current_state = await state.get_state()

    if current_state:
        return


    # =====================================================
    # LOADING
    # =====================================================

    loading = await loading_animation(message)

    try:

        # Beri efek pencarian
        await asyncio.sleep(0.35)

        return await message.answer(
            (
                "🛍 <b>MEDIA TERDETEKSI</b>\n\n"
                "🔎 Media sedang diarahkan ke "
                "<b>Marketplace</b>.\n\n"
                "Semua code dan media yang tersedia "
                "dapat kamu cari melalui Marketplace.\n\n"
                "Tekan tombol di bawah untuk melihat "
                "koleksi yang tersedia."
            ),
            parse_mode="HTML",
            reply_markup=kb_marketplace(),
        )

    finally:

        await delete_loading(loading)


# =========================================================
# FALLBACK
# =========================================================

@router.message()
async def notify_other(
    message: Message,
    state: FSMContext,
):

    current_state = await state.get_state()

    if current_state:
        return


    # =====================================================
    # LOADING
    # =====================================================

    loading = await loading_animation(message)

    try:

        await asyncio.sleep(0.25)

        return await message.answer(
            (
                "🤖 <b>BOT MARKET</b>\n\n"
                "🔎 Pesan sedang diproses.\n\n"
                "Gunakan menu yang tersedia "
                "untuk melanjutkan."
            ),
            parse_mode="HTML",
            reply_markup=kb_home(),
        )

    finally:

        await delete_loading(loading)
