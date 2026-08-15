import logging

from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    Contact,
)

from database import get_pool

ADMIN_ID = 123456789

router = Router()

CREATOR_REQUIRED_REFERRAL = 100


class CreatorApplicationState(StatesGroup):
    waiting_telegram = State()
    waiting_contact = State()
    confirming = State()


# =====================================
# START CREATOR APPLICATION
# =====================================

@router.callback_query(F.data == "creator_apply")
async def creator_apply(
    call: CallbackQuery,
    state: FSMContext
):

    pool = await get_pool()

    user = await pool.fetchrow(
        """
        SELECT
            user_id,
            username,
            fullname,
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

    # =====================================
    # SUDAH KREATOR
    # =====================================

    if is_creator and status == "approved":

        return await call.answer(
            "✅ Kamu sudah menjadi Kreator.",
            show_alert=True
        )

    # =====================================
    # MASIH PENDING
    # =====================================

    if status == "pending":

        return await call.answer(
            "⏳ Pengajuan kamu masih menunggu verifikasi admin.",
            show_alert=True
        )

    # =====================================
    # CEK REFERRAL
    # =====================================

    if referral_count < CREATOR_REQUIRED_REFERRAL:

        remaining = (
            CREATOR_REQUIRED_REFERRAL
            - referral_count
        )

        return await call.answer(
            f"❌ Referral belum cukup.\n\n"
            f"Referral: {referral_count}/"
            f"{CREATOR_REQUIRED_REFERRAL}\n"
            f"Kekurangan: {remaining}",
            show_alert=True
        )

    # =====================================
    # MULAI FORM
    # =====================================

    await state.clear()

    await state.set_state(
        CreatorApplicationState.waiting_telegram
    )

    text = (
        "🎨 <b>VERIFIKASI KREATOR</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"

        "Kamu sudah memenuhi syarat "
        "minimal <b>100 referral</b>. ✅\n\n"

        "Untuk keamanan transaksi dan mencegah "
        "penyalahgunaan pembayaran, kamu harus "
        "melakukan verifikasi terlebih dahulu.\n\n"

        "📱 <b>LANGKAH 1</b>\n\n"
        "Kirim username Telegram yang aktif.\n\n"

        "Contoh:\n"
        "<code>@username</code>\n\n"

        "⚠️ Jangan kirim password, OTP, PIN, "
        "atau informasi rahasia lainnya."
    )

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="❌ Batal",
                    callback_data="creator_cancel"
                )
            ]
        ]
    )

    try:
        await call.message.edit_text(
            text,
            parse_mode="HTML",
            reply_markup=keyboard
        )

    except Exception:

        await call.message.answer(
            text,
            parse_mode="HTML",
            reply_markup=keyboard
        )

    await call.answer()


# =====================================
# TELEGRAM USERNAME
# =====================================

@router.message(
    CreatorApplicationState.waiting_telegram,
    F.text
)
async def creator_telegram(
    message: Message,
    state: FSMContext
):

    username = message.text.strip()

    if not username.startswith("@"):

        username = "@" + username

    if len(username) < 3:

        return await message.answer(
            "❌ Username Telegram tidak valid.\n\n"
            "Contoh: <code>@username</code>",
            parse_mode="HTML"
        )

    await state.update_data(
        telegram_username=username
    )

    await state.set_state(
        CreatorApplicationState.waiting_contact
    )

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="❌ Batal",
                    callback_data="creator_cancel"
                )
            ]
        ]
    )

    await message.answer(
        "📞 <b>LANGKAH 2 — KONTAK</b>\n\n"
        "Kirim nomor WhatsApp/telepon yang aktif "
        "untuk keperluan verifikasi.\n\n"
        "Contoh:\n"
        "<code>628123456789</code>\n\n"
        "⚠️ Nomor hanya digunakan untuk proses "
        "verifikasi Kreator.",
        parse_mode="HTML",
        reply_markup=keyboard
    )


# =====================================
# CONTACT
# =====================================

@router.message(
    CreatorApplicationState.waiting_contact,
    F.contact
)
async def creator_contact(
    message: Message,
    state: FSMContext
):

    contact = message.contact

    if not contact.phone_number:

        return await message.answer(
            "❌ Nomor kontak tidak ditemukan."
        )

    await save_creator_contact(
        message,
        state,
        contact.phone_number
    )


@router.message(
    CreatorApplicationState.waiting_contact,
    F.text
)
async def creator_contact_text(
    message: Message,
    state: FSMContext
):

    phone = message.text.strip()

    if len(phone) < 8:

        return await message.answer(
            "❌ Nomor tidak valid.\n\n"
            "Silakan kirim nomor WhatsApp/telepon "
            "yang aktif."
        )

    await save_creator_contact(
        message,
        state,
        phone
    )


async def save_creator_contact(
    message: Message,
    state: FSMContext,
    phone: str
):

    await state.update_data(
        contact=phone
    )

    data = await state.get_data()

    telegram_username = data.get(
        "telegram_username",
        "-"
    )

    await state.set_state(
        CreatorApplicationState.confirming
    )

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Kirim Verifikasi",
                    callback_data="creator_submit"
                )
            ],
            [
                InlineKeyboardButton(
                    text="✏️ Ubah",
                    callback_data="creator_restart"
                ),
                InlineKeyboardButton(
                    text="❌ Batal",
                    callback_data="creator_cancel"
                )
            ]
        ]
    )

    await message.answer(
        "🔎 <b>KONFIRMASI DATA KREATOR</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"

        f"📱 Telegram : "
        f"<b>{telegram_username}</b>\n"

        f"📞 Kontak : "
        f"<code>{phone}</code>\n\n"

        "👥 Syarat referral : <b>100+</b>\n\n"

        "Pastikan data di atas benar sebelum "
        "mengirim pengajuan.\n\n"

        "⚠️ Jangan mengirim password, OTP, PIN, "
        "atau data pembayaran.",
        parse_mode="HTML",
        reply_markup=keyboard
    )


# =====================================
# SUBMIT
# =====================================

@router.callback_query(
    CreatorApplicationState.confirming,
    F.data == "creator_submit"
)
async def creator_submit(
    call: CallbackQuery,
    state: FSMContext
):

    pool = await get_pool()

    data = await state.get_data()

    telegram_username = data.get(
        "telegram_username"
    )

    contact = data.get(
        "contact"
    )

    # =====================================
    # CEK DATA FORM
    # =====================================

    if not telegram_username or not contact:

        return await call.answer(
            "❌ Data verifikasi belum lengkap.",
            show_alert=True
        )

    # =====================================
    # AMBIL DATA USER
    # =====================================

    user = await pool.fetchrow(
        """
        SELECT
            user_id,
            username,
            fullname,
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

    # =====================================
    # CEK REFERRAL
    # =====================================

    if referral_count < CREATOR_REQUIRED_REFERRAL:

        await state.clear()

        return await call.answer(
            "❌ Syarat referral sudah tidak terpenuhi.",
            show_alert=True
        )

    # =====================================
    # CEK PENDING
    # =====================================

    if user["creator_status"] == "pending":

        await state.clear()

        return await call.answer(
            "⏳ Pengajuan kamu sudah menunggu verifikasi.",
            show_alert=True
        )

    # =====================================
    # SIMPAN DATA KREATOR
    # =====================================

    await pool.execute(
        """
        UPDATE users
        SET
            creator_status = 'pending',
            is_creator = FALSE,
            phone = $2,
            creator_telegram = $3,
            updated_at = NOW()
        WHERE user_id = $1
        """,
        call.from_user.id,
        contact,
        telegram_username
    )

    # =====================================
    # BUAT NOTIFIKASI ADMIN
    # =====================================

    admin_text = (
        "🎨 <b>PENGAJUAN KREATOR BARU</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"

        f"👤 User : <b>{user['fullname'] or '-'}</b>\n"
        f"🆔 ID : <code>{user['user_id']}</code>\n"
        f"🔗 Username : "
        f"<b>{user['username'] or '-'}</b>\n\n"

        f"👥 Referral : "
        f"<b>{referral_count}</b>\n\n"

        f"📱 Telegram : "
        f"<b>{telegram_username}</b>\n"

        f"📞 Kontak : "
        f"<code>{contact}</code>\n\n"

        "⏳ Status : <b>PENDING</b>"
    )

    admin_keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ TERIMA",
                    callback_data=(
                        f"creator_approve:{user['user_id']}"
                    )
                ),
                InlineKeyboardButton(
                    text="❌ TOLAK",
                    callback_data=(
                        f"creator_reject:{user['user_id']}"
                    )
                )
            ]
        ]
    )

    # =====================================
    # KIRIM KE ADMIN
    # =====================================

    try:

        await call.bot.send_message(
            chat_id=ADMIN_ID,
            text=admin_text,
            parse_mode="HTML",
            reply_markup=admin_keyboard
        )

    except Exception:

        logging.exception(
            "Gagal mengirim pengajuan Kreator ke admin"
        )

        # Kalau gagal kirim ke admin,
        # jangan biarkan user mengira sudah berhasil.

        await pool.execute(
            """
            UPDATE users
            SET
                creator_status = 'none',
                is_creator = FALSE
            WHERE user_id = $1
            """,
            call.from_user.id
        )

        return await call.answer(
            "❌ Gagal mengirim pengajuan ke admin.",
            show_alert=True
        )

    # =====================================
    # SELESAI
    # =====================================

    await state.clear()

    await call.message.edit_text(
        "🎨 <b>PENGAJUAN TERKIRIM</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"

        "✅ Data verifikasi berhasil dikirim.\n\n"

        "⏳ Status : <b>Menunggu Verifikasi</b>\n\n"

        "Pengajuan kamu sudah dikirim ke admin.\n"
        "Admin akan memeriksa data kamu terlebih "
        "dahulu sebelum memberikan status Kreator.\n\n"

        "Mohon tunggu sampai proses verifikasi selesai.",
        parse_mode="HTML"
    )

    await call.answer(
        "✅ Pengajuan berhasil dikirim."
    )


# =====================================
# RESTART
# =====================================

@router.callback_query(
    F.data == "creator_restart"
)
async def creator_restart(
    call: CallbackQuery,
    state: FSMContext
):

    await state.clear()

    await state.set_state(
        CreatorApplicationState.waiting_telegram
    )

    await call.message.edit_text(
        "📱 <b>ULANGI VERIFIKASI</b>\n\n"
        "Kirim username Telegram kamu.\n\n"
        "Contoh:\n"
        "<code>@username</code>",
        parse_mode="HTML"
    )

    await call.answer()


# =====================================
# CANCEL
# =====================================

@router.callback_query(F.data == "creator_cancel")
async def creator_cancel(
    call: CallbackQuery,
    state: FSMContext
):

    await state.clear()

    await call.message.edit_text(
        "❌ <b>Verifikasi Kreator dibatalkan.</b>\n\n"
        "Kamu bisa mengajukan kembali kapan saja "
        "jika sudah memenuhi syarat.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="👤 Account",
                        callback_data="account"
                    )
                ]
            ]
        )
    )

    await call.answer()
