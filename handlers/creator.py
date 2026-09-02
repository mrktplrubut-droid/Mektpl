import logging
import os
import qrcode
from io import BytesIO

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
from config import ADMIN_IDS, MANUAL_QR_FILE_ID

ADMIN_ID = ADMIN_IDS[0] if ADMIN_IDS else 0

router = Router()

CREATOR_REQUIRED_REFERRAL = 100
# Harga upgrade Kreator dapat diubah tanpa menyentuh kode.
CREATOR_UPGRADE_PRICE = int(os.getenv("CREATOR_UPGRADE_PRICE", "50000"))


def rupiah(value: int) -> str:
    try:
        return f"Rp {int(value):,}".replace(",", ".")
    except (TypeError, ValueError):
        return "Rp 0"


class CreatorApplicationState(StatesGroup):
    waiting_telegram = State()
    waiting_contact = State()
    confirming = State()


@router.callback_query(F.data == "creator")
async def creator_info(call: CallbackQuery):
    pool = await get_pool()
    user = await pool.fetchrow(
        "SELECT referral_count,is_creator,creator_status FROM users WHERE user_id=$1",
        call.from_user.id
    )
    if not user:
        return await call.answer("❌ Data akun tidak ditemukan.", show_alert=True)

    count = int(user["referral_count"] or 0)
    approved = bool(user["is_creator"]) and user["creator_status"] == "approved"
    if approved:
        text = (
            "🎨 <b>PROGRAM KREATOR</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "✅ Status: <b>Kreator Terverifikasi</b>\n\n"
            "🚀 <b>Manfaat:</b>\n"
            "• 📂 Bisa membuka code PAID tanpa membayar\n"
            "• 💰 Bisa upload code dan menentukan harga sendiri\n"
            "• 🛒 Mendapat penghasilan saat code dibeli\n"
            "• 💳 Pendapatan masuk ke saldo dan dapat di-WD sesuai ketentuan\n"
            "• 📊 Penjualan, terlihat, suka, tidak suka, dan rating tercatat real di database\n"
            "• 📤 Bisa membagikan code untuk mendapatkan pembeli\n\n"
            "💡 <b>Tips:</b> Buat preview/review yang jelas agar lebih mudah dipercaya pembeli."
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📤 Upload Code", callback_data="upfile")],
            [InlineKeyboardButton(text="🛍 Marketplace", callback_data="marketplace")],
            [InlineKeyboardButton(text="⬅️ Home", callback_data="home")]
        ])
    else:
        remaining = max(0, CREATOR_REQUIRED_REFERRAL - count)
        text = (
            "🎨 <b>PROGRAM KREATOR</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "Jadilah Kreator dan dapatkan penghasilan dari code yang kamu bagikan.\n\n"
            "✨ <b>Manfaat Kreator:</b>\n"
            "• 📂 Bisa membuka code PAID tanpa bayar setelah terverifikasi\n"
            "• 💰 Bisa upload code PAID dan memasang harga sendiri\n"
            "• 🛒 Saldo bertambah ketika code berhasil dibeli\n"
            "• 💳 Saldo dapat di-WD sesuai ketentuan\n"
            "• 📈 Statistik terlihat, terjual, suka, tidak suka, favorit, dan rating tersimpan real\n"
            "• 📤 Bisa share code untuk mencari pembeli\n\n"
            f"👥 Referral: <b>{count}/{CREATOR_REQUIRED_REFERRAL}</b>\n"
            f"📌 Kekurangan: <b>{remaining}</b> referral\n\n"
            "Setelah memenuhi 100 referral, ajukan verifikasi Kreator."
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💎 Upgrade Creator", callback_data="creator_upgrade")],
            [InlineKeyboardButton(text="🎨 Ajukan Kreator", callback_data="creator_apply")],
            [InlineKeyboardButton(text="⬅️ Home", callback_data="home")]
        ])
    await call.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    await call.answer()



# =====================================
# CREATOR UPGRADE — MANUAL QR
# =====================================

@router.callback_query(F.data == "creator_upgrade")
async def creator_upgrade(call: CallbackQuery):
    """Buat transaksi upgrade Kreator dan tampilkan QR manual."""
    await call.answer()

    pool = await get_pool()
    user_id = call.from_user.id

    user = await pool.fetchrow(
        """
        SELECT user_id, username, fullname, is_creator, creator_status
        FROM users
        WHERE user_id=$1
        """,
        user_id,
    )

    if not user:
        return await call.message.answer("❌ Data akun tidak ditemukan.")

    if bool(user["is_creator"]) and user["creator_status"] == "approved":
        return await call.answer(
            "✅ Kamu sudah menjadi Kreator.",
            show_alert=True,
        )

    pending = await pool.fetchrow(
        """
        SELECT id, amount, created_at
        FROM creator_upgrade_payments
        WHERE user_id=$1 AND status='pending'
        ORDER BY id DESC
        LIMIT 1
        """,
        user_id,
    )

    if pending:
        return await call.answer(
            f"⏳ Masih ada pembayaran upgrade yang menunggu verifikasi.\nID: CREATOR-{pending['id']}",
            show_alert=True,
        )

    try:
        tx = await pool.fetchrow(
            """
            INSERT INTO creator_upgrade_payments
                (user_id, amount, status)
            VALUES ($1, $2, 'pending')
            RETURNING id
            """,
            user_id,
            CREATOR_UPGRADE_PRICE,
        )
    except Exception:
        logging.exception("CREATOR UPGRADE INSERT ERROR")
        return await call.message.answer(
            "❌ Gagal membuat pembayaran upgrade. Silakan coba lagi."
        )

    tx_id = tx["id"]
    caption = (
        "💎 <b>UPGRADE CREATOR</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        f"💰 Nominal: <b>{rupiah(CREATOR_UPGRADE_PRICE)}</b>\n"
        f"🧾 ID Pembayaran: <code>CREATOR-{tx_id}</code>\n\n"
        "1. Scan QR manual di atas.\n"
        "2. Bayar <b>tepat sesuai nominal</b>.\n"
        "3. Setelah transfer, tekan <b>✅ Saya Sudah Bayar</b>.\n"
        "4. Admin akan mengecek pembayaran secara manual.\n\n"
        "🎨 Setelah disetujui, akun langsung menjadi <b>Kreator Terverifikasi</b>.\n"
        "⚠️ Jangan mengirim OTP, PIN, password, atau data rahasia."
    )

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(
                text="✅ Saya Sudah Bayar",
                callback_data=f"creator_upgrade_check:{tx_id}",
            )],
            [InlineKeyboardButton(
                text="❌ Batal",
                callback_data=f"creator_upgrade_cancel:{tx_id}",
            )],
            [InlineKeyboardButton(
                text="⬅️ Kembali",
                callback_data="creator",
            )],
        ]
    )

    try:
        await call.message.delete()
    except Exception:
        pass

    try:
        await call.message.answer_photo(
            MANUAL_QR_FILE_ID,
            caption=caption,
            parse_mode="HTML",
            reply_markup=kb,
        )
    except Exception:
        logging.exception("CREATOR MANUAL QR SEND ERROR")
        await call.message.answer(
            caption + "\n\n⚠️ QR tidak dapat ditampilkan. Hubungi admin.",
            parse_mode="HTML",
            reply_markup=kb,
        )


@router.callback_query(F.data.startswith("creator_upgrade_check:"))
async def creator_upgrade_check(call: CallbackQuery):
    """User mengonfirmasi sudah membayar -> kirim notifikasi ke semua admin."""
    await call.answer()

    try:
        tx_id = int(call.data.split(":", 1)[1])
    except (ValueError, IndexError):
        return await call.answer("❌ ID pembayaran tidak valid.", show_alert=True)

    pool = await get_pool()
    tx = await pool.fetchrow(
        """
        SELECT *
        FROM creator_upgrade_payments
        WHERE id=$1 AND user_id=$2 AND status='pending'
        """,
        tx_id,
        call.from_user.id,
    )

    if not tx:
        return await call.answer(
            "❌ Pembayaran tidak ditemukan atau sudah diproses.",
            show_alert=True,
        )

    user = await pool.fetchrow(
        """
        SELECT username, fullname
        FROM users
        WHERE user_id=$1
        """,
        tx["user_id"],
    )

    admin_text = (
        "💎 <b>UPGRADE CREATOR — PEMBAYARAN MASUK</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        f"👤 Nama: <b>{user['fullname'] if user else '-'}</b>\n"
        f"🆔 User ID: <code>{tx['user_id']}</code>\n"
        f"🔗 Username: <b>@{user['username']}</b>\n" if user and user["username"] else
        "💎 <b>UPGRADE CREATOR — PEMBAYARAN MASUK</b>\n━━━━━━━━━━━━━━━━━━\n\n"
        f"👤 Nama: <b>{user['fullname'] if user else '-'}</b>\n"
        f"🆔 User ID: <code>{tx['user_id']}</code>\n"
    )
    admin_text += (
        f"💰 Nominal: <b>{rupiah(tx['amount'])}</b>\n"
        f"🧾 ID: <code>CREATOR-{tx['id']}</code>\n"
        f"📅 Dibuat: <code>{tx['created_at']}</code>\n\n"
        "🔎 Silakan cek mutasi/pembayaran terlebih dahulu."
    )

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ APPROVE & UPGRADE",
                    callback_data=f"creator_upgrade_approve:{tx_id}",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="❌ FAILED / TOLAK",
                    callback_data=f"creator_upgrade_failed:{tx_id}",
                ),
            ],
        ]
    )

    sent = 0
    for admin_id in ADMIN_IDS:
        try:
            await call.bot.send_message(
                admin_id,
                admin_text,
                parse_mode="HTML",
                reply_markup=kb,
            )
            sent += 1
        except Exception:
            logging.exception("CREATOR UPGRADE ADMIN NOTIFY ERROR admin=%s", admin_id)

    if sent:
        await call.message.edit_caption(
            caption=(
                "⏳ <b>MENUNGGU VERIFIKASI ADMIN</b>\n\n"
                f"🧾 ID: <code>CREATOR-{tx_id}</code>\n"
                f"💰 Nominal: <b>{rupiah(tx['amount'])}</b>\n\n"
                "Pembayaran sudah dilaporkan ke admin. "
                "Tunggu sampai admin menyetujui."
            ),
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="⬅️ Kreator", callback_data="creator")]
                ]
            ),
        )
        return

    await call.message.answer("❌ Admin tidak dapat menerima notifikasi. Coba lagi.")


@router.callback_query(F.data.startswith("creator_upgrade_cancel:"))
async def creator_upgrade_cancel(call: CallbackQuery):
    await call.answer()
    try:
        tx_id = int(call.data.split(":", 1)[1])
    except (ValueError, IndexError):
        return await call.answer("❌ ID pembayaran tidak valid.", show_alert=True)

    pool = await get_pool()
    await pool.execute(
        """
        UPDATE creator_upgrade_payments
        SET status='cancelled', reviewed_at=NOW()
        WHERE id=$1 AND user_id=$2 AND status='pending'
        """,
        tx_id,
        call.from_user.id,
    )
    await call.message.edit_text(
        "❌ <b>Pembayaran upgrade dibatalkan.</b>\n\n"
        "Kamu bisa membuat pembayaran baru kapan saja.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="🎨 Kembali ke Kreator", callback_data="creator")]]
        ),
    )


@router.callback_query(F.data.startswith("creator_upgrade_approve:"))
async def creator_upgrade_approve(call: CallbackQuery):
    if call.from_user.id not in ADMIN_IDS:
        return await call.answer("❌ Kamu tidak memiliki akses.", show_alert=True)

    await call.answer()
    try:
        tx_id = int(call.data.split(":", 1)[1])
    except (ValueError, IndexError):
        return await call.answer("❌ ID pembayaran tidak valid.", show_alert=True)

    pool = await get_pool()
    tx = await pool.fetchrow(
        """
        UPDATE creator_upgrade_payments
        SET status='approved', admin_id=$1, reviewed_at=NOW(), paid_at=NOW()
        WHERE id=$2 AND status='pending'
        RETURNING *
        """,
        call.from_user.id,
        tx_id,
    )
    if not tx:
        return await call.answer("❌ Pembayaran sudah diproses / tidak ditemukan.", show_alert=True)

    await pool.execute(
        """
        UPDATE users
        SET is_creator=TRUE,
            creator_status='approved',
            creator_verified_at=NOW(),
            updated_at=NOW()
        WHERE user_id=$1
        """,
        tx["user_id"],
    )

    try:
        await call.bot.send_message(
            tx["user_id"],
            "🎉 <b>UPGRADE CREATOR BERHASIL!</b>\n\n"
            "✅ Pembayaran kamu telah diverifikasi admin.\n"
            "🎨 Akun kamu sekarang resmi menjadi <b>Kreator Terverifikasi</b>.\n\n"
            "📤 Kamu dapat upload code berbayar.\n"
            "💰 Kamu dapat memperoleh penghasilan dari penjualan.\n"
            "📊 Kelola code dan penjualan dari fitur Kreator.",
            parse_mode="HTML",
        )
    except Exception:
        logging.exception("CREATOR UPGRADE USER NOTIFY ERROR")

    try:
        await call.message.edit_text(
            "✅ <b>UPGRADE CREATOR DISETUJUI</b>\n\n"
            f"👤 User: <code>{tx['user_id']}</code>\n"
            f"💰 Nominal: <b>{rupiah(tx['amount'])}</b>\n"
            f"🧾 ID: <code>CREATOR-{tx['id']}</code>\n"
            f"👮 Admin: <code>{call.from_user.id}</code>",
            parse_mode="HTML",
        )
    except Exception:
        pass


@router.callback_query(F.data.startswith("creator_upgrade_failed:"))
async def creator_upgrade_failed(call: CallbackQuery):
    if call.from_user.id not in ADMIN_IDS:
        return await call.answer("❌ Kamu tidak memiliki akses.", show_alert=True)

    await call.answer()
    try:
        tx_id = int(call.data.split(":", 1)[1])
    except (ValueError, IndexError):
        return await call.answer("❌ ID pembayaran tidak valid.", show_alert=True)

    pool = await get_pool()
    tx = await pool.fetchrow(
        """
        UPDATE creator_upgrade_payments
        SET status='failed', admin_id=$1, reviewed_at=NOW()
        WHERE id=$2 AND status='pending'
        RETURNING *
        """,
        call.from_user.id,
        tx_id,
    )
    if not tx:
        return await call.answer("❌ Pembayaran sudah diproses / tidak ditemukan.", show_alert=True)

    try:
        await call.bot.send_message(
            tx["user_id"],
            "⚠️ <b>PEMBAYARAN UPGRADE CREATOR BELUM DISETUJUI</b>\n\n"
            f"🧾 ID: <code>CREATOR-{tx['id']}</code>\n"
            "Admin tidak menemukan pembayaran yang sesuai atau pembayaran belum masuk.\n"
            "Silakan hubungi admin jika kamu yakin sudah membayar.",
            parse_mode="HTML",
        )
    except Exception:
        logging.exception("CREATOR UPGRADE FAILED USER NOTIFY ERROR")

    try:
        await call.message.edit_text(
            "❌ <b>UPGRADE CREATOR DITOLAK</b>\n\n"
            f"👤 User: <code>{tx['user_id']}</code>\n"
            f"🧾 ID: <code>CREATOR-{tx['id']}</code>\n"
            f"👮 Admin: <code>{call.from_user.id}</code>",
            parse_mode="HTML",
        )
    except Exception:
        pass


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



# =====================================
# ADMIN APPROVE CREATOR
# =====================================

@router.callback_query(
    F.data.startswith("creator_approve:")
)
async def creator_approve(
    call: CallbackQuery
):

    # Hanya admin yang boleh memproses
    if call.from_user.id not in ADMIN_IDS:

        return await call.answer(
            "❌ Kamu tidak memiliki akses.",
            show_alert=True
        )

    try:
        user_id = int(
            call.data.split(":", 1)[1]
        )
    except (ValueError, IndexError):

        return await call.answer(
            "❌ Data user tidak valid.",
            show_alert=True
        )

    pool = await get_pool()

    user = await pool.fetchrow(
        """
        SELECT
            user_id,
            username,
            fullname,
            creator_status
        FROM users
        WHERE user_id = $1
        """,
        user_id
    )

    if not user:

        return await call.answer(
            "❌ User tidak ditemukan.",
            show_alert=True
        )

    # Sudah diterima sebelumnya
    if user["creator_status"] == "approved":

        return await call.answer(
            "✅ User ini sudah menjadi Kreator.",
            show_alert=True
        )

    # =====================================
    # APPROVE
    # =====================================

    await pool.execute(
        """
        UPDATE users
        SET
            is_creator = TRUE,
            creator_status = 'approved',
            creator_verified_at = NOW(),
            updated_at = NOW()
        WHERE user_id = $1
        """,
        user_id
    )

    # =====================================
    # UPDATE PESAN ADMIN
    # =====================================

    try:

        await call.message.edit_text(
            call.message.text
            + "\n\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "✅ <b>DITERIMA</b>\n"
            f"👮 Admin : <code>{call.from_user.id}</code>",
            parse_mode="HTML"
        )

    except Exception:
        pass

    # =====================================
    # NOTIFIKASI USER
    # =====================================

    try:

        await call.bot.send_message(
            chat_id=user_id,
            text=(
                "🎉 <b>SELAMAT!</b>\n"
                "━━━━━━━━━━━━━━━━━━\n\n"

                "✅ Pengajuan Kreator kamu "
                "telah <b>DISETUJUI</b>.\n\n"

                "🎨 Sekarang kamu resmi menjadi "
                "<b>Kreator</b>.\n\n"

                "Kamu sekarang dapat:\n"
                "📤 Upload file berbayar\n"
                "💰 Mendapatkan penghasilan dari penjualan\n"
                "📊 Mengelola file Marketplace\n\n"

                "⚠️ Untuk file berbayar, tetap ikuti "
                "aturan dan proses review yang berlaku."
            ),
            parse_mode="HTML"
        )

    except Exception:

        logging.exception(
            "Gagal mengirim notifikasi approval Kreator"
        )

    await call.answer(
        "✅ User berhasil menjadi Kreator.",
        show_alert=True
    )


# =====================================
# ADMIN REJECT CREATOR
# =====================================

@router.callback_query(
    F.data.startswith("creator_reject:")
)
async def creator_reject(
    call: CallbackQuery
):

    # Hanya admin
    if call.from_user.id not in ADMIN_IDS:

        return await call.answer(
            "❌ Kamu tidak memiliki akses.",
            show_alert=True
        )

    try:
        user_id = int(
            call.data.split(":", 1)[1]
        )
    except (ValueError, IndexError):

        return await call.answer(
            "❌ Data user tidak valid.",
            show_alert=True
        )

    pool = await get_pool()

    user = await pool.fetchrow(
        """
        SELECT
            user_id,
            username,
            fullname,
            creator_status
        FROM users
        WHERE user_id = $1
        """,
        user_id
    )

    if not user:

        return await call.answer(
            "❌ User tidak ditemukan.",
            show_alert=True
        )

    # =====================================
    # REJECT
    # =====================================

    await pool.execute(
        """
        UPDATE users
        SET
            is_creator = FALSE,
            creator_status = 'rejected',
            updated_at = NOW()
        WHERE user_id = $1
        """,
        user_id
    )

    # =====================================
    # UPDATE PESAN ADMIN
    # =====================================

    try:

        await call.message.edit_text(
            call.message.text
            + "\n\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "❌ <b>DITOLAK</b>\n"
            f"👮 Admin : <code>{call.from_user.id}</code>",
            parse_mode="HTML"
        )

    except Exception:
        pass

    # =====================================
    # NOTIFIKASI USER
    # =====================================

    try:

        await call.bot.send_message(
            chat_id=user_id,
            text=(
                "⚠️ <b>PENGAJUAN KREATOR</b>\n"
                "━━━━━━━━━━━━━━━━━━\n\n"

                "❌ Pengajuan Kreator kamu "
                "belum disetujui oleh admin.\n\n"

                "Kamu dapat mengajukan kembali "
                "setelah memperbaiki data atau "
                "memenuhi persyaratan yang diperlukan."
            ),
            parse_mode="HTML"
        )

    except Exception:

        logging.exception(
            "Gagal mengirim notifikasi penolakan Kreator"
        )

    await call.answer(
        "❌ Pengajuan ditolak.",
        show_alert=True
    )
