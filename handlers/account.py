from aiogram import Router, F
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton
)

from database import get_pool
from urllib.parse import quote
from config import BOT_USERNAME
from keyboards.menu import account_kb


router = Router()

CREATOR_REQUIRED_REFERRAL = 100


# =====================================
# OPEN ACCOUNT
# =====================================

async def open_account(
    message: Message,
    user_id: int
):

    pool = await get_pool()

    user = await pool.fetchrow(
        """
        SELECT
            referral_count,
            is_creator,
            creator_status,
            creator_verified_at,
            balance
        FROM users
        WHERE user_id = $1
        """,
        user_id
    )

    if not user:

        return await message.edit_text(
            "❌ Data akun tidak ditemukan."
        )

    referral_count = (
        user["referral_count"] or 0
    )

    is_creator = bool(
        user["is_creator"]
    )

    creator_status = (
        user["creator_status"] or "none"
    )

    creator_verified_at = (
        user["creator_verified_at"]
    )

    balance = user["balance"] or 0

    # =====================================
    # REFERRAL LINK
    # =====================================

    ref_link = (
        f"https://t.me/{BOT_USERNAME}"
        f"?start=ref_{user_id}"
    )

    # =====================================
    # STATUS KREATOR
    # =====================================

    if (
        is_creator
        and creator_status == "approved"
    ):

        creator_text = (
            "🎨 <b>STATUS KREATOR</b>\n"
            "✅ <b>Terverifikasi</b>\n"
        )

        if creator_verified_at:

            creator_text += (
                f"📅 Verifikasi : "
                f"<b>{creator_verified_at:%d-%m-%Y}</b>\n"
            )

        creator_button = InlineKeyboardButton(
            text="🎨 Kreator ✅",
            callback_data="creator_status"
        )

    elif creator_status == "pending":

        creator_text = (
            "🎨 <b>STATUS KREATOR</b>\n"
            "⏳ <b>Menunggu Verifikasi Admin</b>\n"
        )

        creator_button = InlineKeyboardButton(
            text="🎨 Kreator ⏳",
            callback_data="creator_status"
        )

    elif creator_status == "rejected":

        creator_text = (
            "🎨 <b>STATUS KREATOR</b>\n"
            "❌ <b>Pengajuan Ditolak</b>\n"
        )

        creator_button = InlineKeyboardButton(
            text="🎨 Ajukan Kembali",
            callback_data="creator_apply"
        )

    elif (
        referral_count
        >= CREATOR_REQUIRED_REFERRAL
    ):

        creator_text = (
            "🎨 <b>STATUS KREATOR</b>\n"
            "🔓 <b>Syarat Terpenuhi</b>\n"
            f"👥 Referral : "
            f"<b>{referral_count}/"
            f"{CREATOR_REQUIRED_REFERRAL}</b>\n"
        )

        creator_button = InlineKeyboardButton(
            text="🎨 Ajukan Kreator",
            callback_data="creator_apply"
        )

    else:

        remaining = (
            CREATOR_REQUIRED_REFERRAL
            - referral_count
        )

        creator_text = (
            "🎨 <b>STATUS KREATOR</b>\n"
            "🔒 <b>Belum Memenuhi Syarat</b>\n"
            f"👥 Referral : "
            f"<b>{referral_count}/"
            f"{CREATOR_REQUIRED_REFERRAL}</b>\n"
            f"📊 Kekurangan : "
            f"<b>{remaining} referral</b>\n"
        )

        creator_button = InlineKeyboardButton(
            text="🎨 Status Kreator",
            callback_data="creator_status"
        )

    # =====================================
    # ACCOUNT TEXT
    # =====================================

    text = (
        "👤 <b>ACCOUNT INFO</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"

        f"🆔 <b>User ID</b>\n"
        f"<code>{user_id}</code>\n\n"

        f"💰 <b>Saldo</b>\n"
        f"<b>Rp {balance:,}</b>\n\n"

        "🎯 <b>REFERRAL</b>\n"
        f"👥 Total Undangan : "
        f"<b>{referral_count}</b>\n\n"

        "🔗 <b>Link Referral</b>\n"
        f"<code>{ref_link}</code>\n\n"

        f"{creator_text}\n"
    )

    # =====================================
    # KEYBOARD — clean, role-aware account menu
    # =====================================
    lang = (await pool.fetchval("SELECT language FROM users WHERE user_id=$1", user_id)) or "id"
    menu = account_kb(
        lang=lang,
        is_creator=(is_creator and creator_status == "approved")
    )
    # Keep referral sharing as a separate action above the role menu.
    share_text = quote("🤖 Gabung marketplace bot saya! Upload, jual, beli, dan bagikan code Telegram.")
    share_url = f"https://t.me/share/url?url={quote(ref_link)}&text={share_text}"
    menu.inline_keyboard.insert(0, [InlineKeyboardButton(text="📤 Bagikan Referral" if lang == "id" else "📤 Share Referral", url=share_url)])


    await message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=kb,
        disable_web_page_preview=True
    )


# =====================================
# ACCOUNT CALLBACK
# =====================================

@router.callback_query(
    F.data == "account"
)
async def account_handler(
    call: CallbackQuery
):

    await open_account(
        call.message,
        call.from_user.id
    )

    await call.answer()


# =====================================
# ACCOUNT REPLY BUTTON
# =====================================

@router.message(
    F.text.in_(
        ["👤 Akun", "👤 Account"]
    )
)
async def account(
    message: Message
):

    loading = await message.answer(
        "⏳ Loading..."
    )

    await open_account(
        loading,
        message.from_user.id
    )


# =====================================
# WITHDRAW LOCKED
# =====================================

@router.callback_query(
    F.data == "withdraw_locked"
)
async def withdraw_locked(
    call: CallbackQuery
):

    pool = await get_pool()

    user = await pool.fetchrow(
        """
        SELECT
            referral_count,
            is_creator,
            creator_status
        FROM users
        WHERE user_id = $1
        """,
        call.from_user.id
    )

    if not user:

        return await call.answer(
            "❌ Data akun tidak ditemukan.",
            show_alert=True
        )

    referral_count = (
        user["referral_count"] or 0
    )

    is_creator = bool(
        user["is_creator"]
    )

    creator_status = (
        user["creator_status"] or "none"
    )

    # =====================================
    # SUDAH KREATOR
    # =====================================

    if (
        is_creator
        and creator_status == "approved"
    ):

        return await call.answer(
            "✅ Kamu sudah menjadi Kreator.\n"
            "Silakan buka menu Withdraw.",
            show_alert=True
        )

    # =====================================
    # PENDING
    # =====================================

    if creator_status == "pending":

        return await call.answer(
            "⏳ Pengajuan Kreator kamu sedang "
            "diperiksa oleh admin.\n\n"
            "Withdraw akan terbuka setelah "
            "verifikasi disetujui.",
            show_alert=True
        )

    # =====================================
    # SUDAH 100 REFERRAL
    # =====================================

    if (
        referral_count
        >= CREATOR_REQUIRED_REFERRAL
    ):

        return await call.answer(
            "🔒 Withdraw masih terkunci.\n\n"
            "Kamu sudah memenuhi 100 referral. "
            "Silakan ajukan verifikasi Kreator.",
            show_alert=True
        )

    # =====================================
    # BELUM CUKUP
    # =====================================

    remaining = (
        CREATOR_REQUIRED_REFERRAL
        - referral_count
    )

    await call.answer(
        "🔒 <b>WITHDRAW TERKUNCI</b>\n\n"
        "Withdraw hanya tersedia untuk "
        "Kreator terverifikasi.\n\n"
        f"👥 Referral : "
        f"{referral_count}/"
        f"{CREATOR_REQUIRED_REFERRAL}\n"
        f"📊 Kekurangan : "
        f"{remaining} referral",
        show_alert=True
    )


# =====================================
# CREATOR STATUS
# =====================================

@router.callback_query(
    F.data == "creator_status"
)
async def creator_status_handler(
    call: CallbackQuery
):

    pool = await get_pool()

    user = await pool.fetchrow(
        """
        SELECT
            referral_count,
            is_creator,
            creator_status,
            creator_verified_at
        FROM users
        WHERE user_id = $1
        """,
        call.from_user.id
    )

    if not user:

        return await call.answer(
            "❌ Data akun tidak ditemukan.",
            show_alert=True
        )

    referral_count = (
        user["referral_count"] or 0
    )

    is_creator = bool(
        user["is_creator"]
    )

    status = (
        user["creator_status"] or "none"
    )

    verified_at = (
        user["creator_verified_at"]
    )

    # =====================================
    # APPROVED
    # =====================================

    if (
        is_creator
        and status == "approved"
    ):

        verified_text = ""

        if verified_at:

            verified_text = (
                f"\n📅 Terverifikasi : "
                f"<b>{verified_at:%d-%m-%Y}</b>\n"
            )

        text = (
            "🎨 <b>STATUS KREATOR</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"

            "Status : "
            "✅ <b>Kreator Terverifikasi</b>\n"

            f"{verified_text}\n"

            f"👥 Referral : "
            f"<b>{referral_count}</b>\n\n"

            "🎉 Kamu sudah resmi menjadi Kreator.\n\n"

            "Kamu dapat:\n"
            "📤 Menjual file berbayar\n"
            "💰 Mendapatkan saldo dari penjualan\n"
            "🏦 Melakukan Withdraw\n"
        )

    # =====================================
    # PENDING
    # =====================================

    elif status == "pending":

        text = (
            "🎨 <b>STATUS KREATOR</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"

            "Status : "
            "⏳ <b>Menunggu Verifikasi</b>\n\n"

            "Pengajuan kamu sedang diperiksa "
            "oleh admin.\n\n"

            "Mohon tunggu sampai proses "
            "verifikasi selesai."
        )

    # =====================================
    # REJECTED
    # =====================================

    elif status == "rejected":

        text = (
            "🎨 <b>STATUS KREATOR</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"

            "Status : ❌ <b>Ditolak</b>\n\n"

            f"👥 Referral : "
            f"<b>{referral_count}/"
            f"{CREATOR_REQUIRED_REFERRAL}</b>\n\n"

            "Kamu dapat mengajukan verifikasi "
            "kembali."
        )

    # =====================================
    # READY
    # =====================================

    elif (
        referral_count
        >= CREATOR_REQUIRED_REFERRAL
    ):

        text = (
            "🎨 <b>STATUS KREATOR</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"

            "Status : 🔓 "
            "<b>Syarat Terpenuhi</b>\n\n"

            f"👥 Referral : "
            f"<b>{referral_count}/"
            f"{CREATOR_REQUIRED_REFERRAL}</b>\n\n"

            "🎉 Kamu sudah memenuhi syarat "
            "untuk menjadi Kreator.\n\n"

            "Silakan lanjutkan proses verifikasi."
        )

    # =====================================
    # NOT ENOUGH
    # =====================================

    else:

        remaining = (
            CREATOR_REQUIRED_REFERRAL
            - referral_count
        )

        text = (
            "🎨 <b>STATUS KREATOR</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"

            "Status : 🔒 "
            "<b>Belum Memenuhi Syarat</b>\n\n"

            f"👥 Referral : "
            f"<b>{referral_count}/"
            f"{CREATOR_REQUIRED_REFERRAL}</b>\n"

            f"📊 Kekurangan : "
            f"<b>{remaining} referral</b>\n\n"

            "Capai 100 referral terlebih dahulu "
            "untuk mengajukan verifikasi."
        )

    # =====================================
    # BUTTON
    # =====================================

    buttons = []

    if (
        not is_creator
        and status in ("none", "rejected")
        and referral_count
        >= CREATOR_REQUIRED_REFERRAL
    ):

        buttons.append(
            [
                InlineKeyboardButton(
                    text="🎨 Ajukan Kreator",
                    callback_data="creator_apply"
                )
            ]
        )

    buttons.append(
        [
            InlineKeyboardButton(
                text="🔙 Account",
                callback_data="account"
            )
        ]
    )

    await call.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=buttons
        )
    )

    await call.answer()


@router.callback_query(F.data == "change_language")
async def change_language(call: CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🇮🇩 Indonesia", callback_data="lang:id"),
        InlineKeyboardButton(text="🇬🇧 English", callback_data="lang:en")
    ], [InlineKeyboardButton(text="🔙 Kembali", callback_data="account")]])
    await call.message.edit_text("🌐 <b>Pilih Bahasa / Choose Language</b>", parse_mode="HTML", reply_markup=kb)
    await call.answer()
