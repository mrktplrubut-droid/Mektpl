from aiogram import Router, F
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton
)

from database import get_pool

router = Router()

BOT_USERNAME = "botmarketRobot"

CREATOR_REQUIRED_REFERRAL = 100


async def open_account(message: Message, user_id: int):

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

    referral_count = user["referral_count"] or 0
    is_creator = bool(user["is_creator"])
    creator_status = user["creator_status"] or "none"
    balance = user["balance"] or 0

    ref_link = (
        f"https://t.me/{BOT_USERNAME}"
        f"?start=ref_{user_id}"
    )

    # =====================================
    # STATUS KREATOR
    # =====================================

    if is_creator and creator_status == "approved":

        creator_text = (
            "🎨 <b>KREATOR</b>\n"
            "✅ Terverifikasi"
        )

        creator_button = InlineKeyboardButton(
            text="🎨 Kreator ✅",
            callback_data="creator_status"
        )

    elif creator_status == "pending":

        creator_text = (
            "🎨 <b>KREATOR</b>\n"
            "⏳ Menunggu Verifikasi"
        )

        creator_button = InlineKeyboardButton(
            text="🎨 Kreator ⏳",
            callback_data="creator_status"
        )

    elif creator_status == "rejected":

        creator_text = (
            "🎨 <b>KREATOR</b>\n"
            "❌ Pengajuan Ditolak"
        )

        creator_button = InlineKeyboardButton(
            text="🎨 Ajukan Kembali",
            callback_data="creator_apply"
        )

    elif referral_count >= CREATOR_REQUIRED_REFERRAL:

        creator_text = (
            "🎨 <b>KREATOR</b>\n"
            "🔓 Syarat Terpenuhi\n"
            f"👥 Referral : "
            f"{referral_count}/{CREATOR_REQUIRED_REFERRAL}"
        )

        creator_button = InlineKeyboardButton(
            text="🎨 Ajukan Kreator",
            callback_data="creator_apply"
        )

    else:

        creator_text = (
            "🎨 <b>KREATOR</b>\n"
            "🔒 Belum Memenuhi Syarat\n"
            f"👥 Referral : "
            f"{referral_count}/{CREATOR_REQUIRED_REFERRAL}"
        )

        creator_button = InlineKeyboardButton(
            text="🎨 Status Kreator",
            callback_data="creator_status"
        )

    # =====================================
    # TEXT ACCOUNT
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
    # KEYBOARD
    # =====================================

    keyboard_rows = [
        [
            InlineKeyboardButton(
                text="📂 My Code",
                callback_data="my_code"
            )
        ],
        [
            creator_button
        ]
    ]

    # =====================================
    # WITHDRAW
    # =====================================

    if is_creator and creator_status == "approved":

        keyboard_rows.append(
            [
                InlineKeyboardButton(
                    text="🏦 Withdraw",
                    callback_data="withdraw"
                )
            ]
        )

    else:

        keyboard_rows.append(
            [
                InlineKeyboardButton(
                    text="🔒 Withdraw",
                    callback_data="withdraw_locked"
                )
            ]
        )

    keyboard_rows.append(
        [
            InlineKeyboardButton(
                text="🔙 Kembali",
                callback_data="home"
            )
        ]
    )

    kb = InlineKeyboardMarkup(
        inline_keyboard=keyboard_rows
    )

    await message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=kb,
        disable_web_page_preview=True
    )


# =====================================
# ACCOUNT CALLBACK
# =====================================

@router.callback_query(F.data == "account")
async def account_handler(call: CallbackQuery):

    await open_account(
        call.message,
        call.from_user.id
    )

    await call.answer()


# =====================================
# ACCOUNT REPLY BUTTON
# =====================================

@router.message(F.text.in_(["👤 Akun", "👤 Account"]))
async def account(message: Message):

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

@router.callback_query(F.data == "withdraw_locked")
async def withdraw_locked(call: CallbackQuery):

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

    referral_count = (
        user["referral_count"]
        if user
        else 0
    )

    is_creator = (
        bool(user["is_creator"])
        if user
        else False
    )

    creator_status = (
        user["creator_status"]
        if user
        else "none"
    )

    if is_creator and creator_status == "approved":

        await call.answer(
            "✅ Kamu sudah menjadi Kreator.",
            show_alert=True
        )

        return

    remaining = max(
        0,
        CREATOR_REQUIRED_REFERRAL - referral_count
    )

    if creator_status == "pending":

        text = (
            "⏳ <b>VERIFIKASI KREATOR</b>\n\n"
            "Pengajuan Kreator kamu sedang "
            "diperiksa oleh admin.\n\n"
            "Mohon tunggu sampai proses verifikasi selesai."
        )

    elif referral_count >= CREATOR_REQUIRED_REFERRAL:

        text = (
            "🔒 <b>WITHDRAW TERKUNCI</b>\n\n"
            "Kamu sudah memenuhi syarat referral "
            "untuk menjadi Kreator.\n\n"
            f"👥 Referral : "
            f"{referral_count}/{CREATOR_REQUIRED_REFERRAL}\n\n"
            "Silakan ajukan verifikasi Kreator "
            "terlebih dahulu."
        )

    else:

        text = (
            "🔒 <b>WITHDRAW TERKUNCI</b>\n\n"
            "Fitur Withdraw hanya tersedia untuk "
            "Kreator yang sudah terverifikasi.\n\n"
            f"👥 Referral : "
            f"{referral_count}/{CREATOR_REQUIRED_REFERRAL}\n"
            f"📊 Kekurangan : {remaining} referral\n\n"
            "Capai 100 referral terlebih dahulu "
            "untuk mengajukan verifikasi Kreator."
        )

    await call.answer(
        text,
        show_alert=True
    )


# =====================================
# CREATOR STATUS
# =====================================

@router.callback_query(F.data == "creator_status")
async def creator_status_handler(
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

    referral_count = user["referral_count"] or 0
    is_creator = bool(user["is_creator"])
    status = user["creator_status"] or "none"

    if is_creator and status == "approved":

        text = (
            "🎨 <b>STATUS KREATOR</b>\n\n"
            "Status : ✅ <b>Kreator Terverifikasi</b>\n\n"
            f"👥 Referral : <b>{referral_count}</b>\n\n"
            "Kamu sudah bisa menjual file berbayar "
            "dan mendapatkan saldo dari penjualan."
        )

    elif status == "pending":

        text = (
            "🎨 <b>STATUS KREATOR</b>\n\n"
            "Status : ⏳ <b>Menunggu Verifikasi</b>\n\n"
            "Pengajuan kamu sedang diperiksa oleh admin."
        )

    elif status == "rejected":

        text = (
            "🎨 <b>STATUS KREATOR</b>\n\n"
            "Status : ❌ <b>Ditolak</b>\n\n"
            "Kamu dapat mengajukan verifikasi kembali."
        )

    elif referral_count >= CREATOR_REQUIRED_REFERRAL:

        text = (
            "🎨 <b>STATUS KREATOR</b>\n\n"
            "Status : 🔓 <b>Syarat Terpenuhi</b>\n\n"
            f"👥 Referral : "
            f"<b>{referral_count}/{CREATOR_REQUIRED_REFERRAL}</b>\n\n"
            "Kamu sudah bisa mengajukan verifikasi Kreator."
        )

    else:

        remaining = (
            CREATOR_REQUIRED_REFERRAL
            - referral_count
        )

        text = (
            "🎨 <b>STATUS KREATOR</b>\n\n"
            "Status : 🔒 <b>Belum Memenuhi Syarat</b>\n\n"
            f"👥 Referral : "
            f"<b>{referral_count}/{CREATOR_REQUIRED_REFERRAL}</b>\n"
            f"📊 Kekurangan : <b>{remaining}</b>\n\n"
            "Capai 100 referral terlebih dahulu."
        )

    buttons = []

    if (
        referral_count >= CREATOR_REQUIRED_REFERRAL
        and status in ("none", "rejected")
        and not is_creator
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
