from __future__ import annotations
import html
import logging
import qrcode
from io import BytesIO
from datetime import datetime, timedelta
from typing import Optional
from aiogram import Router, F
from aiogram.types import (
    CallbackQuery,
    Message,
    BufferedInputFile,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext
from database import get_pool
from utils.bayargg import BayarGG
from config_vip import VIP_PACKAGES
from config import MANUAL_QR_FILE_ID, ADMIN_IDS
from utils.user_lang import get_user_language
from states import VipManualState
logger = logging.getLogger(__name__)
router = Router()
DEFAULT_LANGUAGE = "id"
# ============================================================
# HELPERS
# ============================================================
def rupiah(value: int | float) -> str:
    try:
        return f"Rp {int(value):,}".replace(",", ".")
    except (TypeError, ValueError):
        return "Rp 0"
def safe_html(value) -> str:
    return html.escape(str(value or ""))
def parse_int(value: str) -> Optional[int]:
    """
    Parse angka dari callback_data dengan aman.
    """
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
async def safe_callback_answer(
    call: CallbackQuery,
    text: str | None = None,
    *,
    show_alert: bool = False,
) -> bool:
    """
    Jawab callback dengan aman.
    Penting:
    Callback Telegram harus di-ACK secepat mungkin.
    Error callback expired / invalid tidak boleh membuat bot crash.
    """
    try:
        await call.answer(
            text=text,
            show_alert=show_alert,
        )
        return True
    except TelegramBadRequest as exc:
        error = str(exc).lower()
        if (
            "query is too old" in error
            or "query id is invalid" in error
            or "response timeout expired" in error
        ):
            logger.debug(
                "VIP callback expired/invalid: %s",
                error,
            )
            return False
        logger.warning(
            "VIP callback Telegram error: %s",
            exc,
        )
        return False
    except TelegramForbiddenError:
        return False
    except Exception:
        logger.exception(
            "Unexpected VIP callback answer error"
        )
        return False
async def safe_delete_message(message: Message) -> None:
    try:
        await message.delete()
    except (
        TelegramBadRequest,
        TelegramForbiddenError,
    ):
        pass
    except Exception:
        logger.exception(
            "VIP message delete error"
        )
async def safe_send_message(
    message: Message,
    text: str,
    *,
    reply_markup=None,
    parse_mode: str = "HTML",
) -> bool:
    try:
        await message.answer(
            text,
            parse_mode=parse_mode,
            reply_markup=reply_markup,
        )
        return True
    except (
        TelegramBadRequest,
        TelegramForbiddenError,
    ):
        logger.warning(
            "VIP message send failed"
        )
        return False
    except Exception:
        logger.exception(
            "VIP message send error"
        )
        return False
# ============================================================
# VIP MENU
# ============================================================
def build_vvip(
    lang: str = DEFAULT_LANGUAGE,
):
    lang = lang if lang in ("id", "en") else DEFAULT_LANGUAGE
    kb = InlineKeyboardBuilder()
    for key, paket in VIP_PACKAGES.items():
        name = paket.get(
            "name",
            str(key),
        )
        price = paket.get(
            "price",
            0,
        )
        kb.button(
            text=(
                f"💎 {name} • "
                f"{rupiah(price)}"
            ),
            callback_data=f"buyvip:{key}",
        )
    kb.button(
        text=(
            "🔙 Kembali"
            if lang == "id"
            else "🔙 Back"
        ),
        callback_data="account",
    )
    kb.adjust(1)
    if lang == "id":
        text = (
            "<b>💎 PREMIUM ACCESS</b>\n"
            "━━━━━━━━━━━━━━\n\n"
            "Pilih paket yang sesuai "
            "kebutuhan kamu.\n\n"
            "💠 <b>VIP</b>\n"
            "• Akses fitur premium\n"
            "• Tidak bisa upload\n\n"
            "💎 <b>VVIP</b>\n"
            "• Semua fitur VIP\n"
            "• Bisa upload & simpan media\n"
            "• Fitur premium terbuka\n\n"
            "📷 Pembayaran menggunakan "
            "QR manual."
        )
    else:
        text = (
            "<b>💎 PREMIUM ACCESS</b>\n"
            "━━━━━━━━━━━━━━\n\n"
            "Choose the package you need.\n\n"
            "💠 <b>VIP</b>\n"
            "• Premium access\n"
            "• Upload is not available\n\n"
            "💎 <b>VVIP</b>\n"
            "• All VIP features\n"
            "• Upload & save media\n"
            "• Premium features unlocked\n\n"
            "📷 Payment uses manual QR."
        )
    return text, kb.as_markup()
async def open_vvip(
    message: Message,
    user_id: int,
):
    """
    Membuka menu VIP.
    user_id diberikan secara eksplisit agar tidak salah
    mengambil message.from_user ketika message berasal dari bot.
    """
    try:
        lang = await get_user_language(
            user_id
        )
    except Exception:
        logger.exception(
            "VIP language lookup error"
        )
        lang = DEFAULT_LANGUAGE
    text, markup = build_vvip(lang)
    await message.answer(
        text,
        parse_mode="HTML",
        reply_markup=markup,
    )
# ============================================================
# OPEN VIP FROM REPLY BUTTON
# ============================================================
@router.message(F.text == "💎 Upgrade")
async def vvip_message(
    message: Message,
):
    await open_vvip(
        message,
        message.from_user.id,
    )
# ============================================================
# OPEN VIP FROM ACCOUNT BUTTON
# ============================================================
@router.callback_query(F.data == "vvip")
async def vvip_menu(
    call: CallbackQuery,
):
    # ACK FIRST
    await safe_callback_answer(call)
    if not call.message:
        return
    await open_vvip(
        call.message,
        call.from_user.id,
    )
# ============================================================
# CREATE AUTO PAYMENT
# ============================================================
async def _create_auto_vip(
    call: CallbackQuery,
    paket_id: str,
    paket: dict,
):
    pool = await get_pool()
    user_id = call.from_user.id
    # --------------------------------------------------------
    # CHECK EXISTING PENDING PAYMENT
    # --------------------------------------------------------
    try:
        pending = await pool.fetchrow(
            """
            SELECT invoice_id
            FROM payments
            WHERE user_id = $1
              AND status = 'pending'
              AND (
                  expires_at IS NULL
                  OR expires_at > NOW()
              )
            LIMIT 1
            """,
            user_id,
        )
    except Exception:
        logger.exception(
            "VIP pending payment DB error"
        )
        await call.message.answer(
            "❌ Tidak dapat memeriksa "
            "pembayaran sebelumnya."
        )
        return
    if pending:
        await call.message.answer(
            "⚠️ Masih ada pembayaran VIP "
            "yang belum selesai.\n\n"
            "Selesaikan pembayaran tersebut "
            "atau tunggu sampai kedaluwarsa."
        )
        return
    # --------------------------------------------------------
    # CREATE PAYMENT
    # --------------------------------------------------------
    try:
        payment = await BayarGG.create_payment(
            amount=paket["price"],
            description=(
                f"{paket['name']} - "
                f"{paket['days']} Hari"
            ),
            customer_name=call.from_user.full_name,
        )
    except Exception:
        logger.exception(
            "VIP AUTO PAYMENT ERROR"
        )
        await _manual_fallback(
            call,
            paket_id,
            paket,
            "QR otomatis mengalami gangguan.",
        )
        return
    if not payment:
        await _manual_fallback(
            call,
            paket_id,
            paket,
            "Invoice otomatis gagal dibuat.",
        )
        return
    invoice_id = payment.get(
        "invoice_id"
    )
    qr_string = payment.get(
        "qris_string"
    )
    if not invoice_id:
        await _manual_fallback(
            call,
            paket_id,
            paket,
            "Invoice otomatis tidak valid.",
        )
        return
    # --------------------------------------------------------
    # EXPIRY
    # --------------------------------------------------------
    expires_at = None
    raw_exp = payment.get(
        "expires_at"
    )
    if raw_exp:
        if isinstance(
            raw_exp,
            datetime,
        ):
            expires_at = raw_exp
        else:
            raw_exp = str(
                raw_exp
            ).strip()
            formats = (
                "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%d %H:%M",
                "%Y-%m-%dT%H:%M:%S",
            )
            for fmt in formats:
                try:
                    expires_at = datetime.strptime(
                        raw_exp,
                        fmt,
                    )
                    break
                except ValueError:
                    continue
    # --------------------------------------------------------
    # SAVE PAYMENT
    # --------------------------------------------------------
    try:
        await pool.execute(
            """
            INSERT INTO payments
            (
                order_id,
                user_id,
                code,
                reference,
                amount,
                status,
                provider,
                invoice_id,
                payment_url,
                expires_at,
                type
            )
            VALUES
            (
                $1,
                $2,
                $3,
                $4,
                $5,
                'pending',
                'bayargg',
                $6,
                $7,
                $8,
                $9
            )
            ON CONFLICT (invoice_id)
            DO NOTHING
            """,
            invoice_id,
            user_id,
            paket_id,
            invoice_id,
            paket["price"],
            invoice_id,
            payment.get(
                "payment_url"
            ),
            expires_at,
            paket.get(
                "type",
                "vip",
            ),
        )
    except Exception:
        logger.exception(
            "VIP PAYMENT DB ERROR"
        )
        await _manual_fallback(
            call,
            paket_id,
            paket,
            "Database pembayaran otomatis "
            "bermasalah.",
        )
        return
    # --------------------------------------------------------
    # PAYMENT MESSAGE
    # --------------------------------------------------------
    text = (
        "<b>💳 PEMBAYARAN VIP</b>\n"
        "━━━━━━━━━━━━━━\n\n"
        f"📦 Paket: "
        f"<b>{safe_html(paket['name'])}</b>\n"
        f"💰 Harga: "
        f"<b>{rupiah(paket['price'])}</b>\n"
        f"🧾 Invoice: "
        f"<code>{safe_html(invoice_id)}</code>\n\n"
        "📷 Scan QR otomatis untuk membayar.\n"
        "⚠️ Jika QR otomatis error/"
        "tidak bisa dipakai, tekan "
        "<b>📷 QR Manual</b>.\n\n"
        "Setelah pembayaran berhasil, "
        "VIP akan aktif otomatis."
    )
    kb = InlineKeyboardBuilder()
    kb.button(
        text="⏳ Cek Pembayaran",
        callback_data=(
            f"vipwait:{invoice_id}"
        ),
    )
    kb.button(
        text="📷 QR Manual",
        callback_data=(
            f"vipmanual:{paket_id}"
        ),
    )
    kb.button(
        text="❌ Batal",
        callback_data="vvip",
    )
    kb.adjust(1)
    await safe_delete_message(
        call.message
    )
    # --------------------------------------------------------
    # QR AUTOMATIC
    # --------------------------------------------------------
    if qr_string:
        try:
            qr = qrcode.make(
                qr_string
            )
            buf = BytesIO()
            qr.save(
                buf,
                format="PNG",
            )
            buf.seek(0)
            await call.message.answer_photo(
                BufferedInputFile(
                    buf.getvalue(),
                    filename="vip-qris.png",
                ),
                caption=text,
                parse_mode="HTML",
                reply_markup=kb.as_markup(),
            )
            return
        except Exception:
            logger.exception(
                "VIP QR GENERATION ERROR"
            )
    # --------------------------------------------------------
    # NO QR
    # --------------------------------------------------------
    await call.message.answer(
        text
        + "\n\n⚠️ <b>QR otomatis "
        "tidak tersedia.</b>\n"
        "Gunakan QR Manual di bawah.",
        parse_mode="HTML",
        reply_markup=kb.as_markup(),
    )
# ============================================================
# BUY VIP
# ============================================================
@router.callback_query(
    F.data.startswith("buyvip:")
)
async def buy_vip(
    call: CallbackQuery,
):
    # ACK FIRST
    await safe_callback_answer(call)
    parts = call.data.split(
        ":",
        1,
    )
    if len(parts) != 2:
        return
    paket_id = (
        paket_id_override
        if paket_id_override
        else parts[1].strip()
    )
    paket = VIP_PACKAGES.get(
        paket_id
    )
    if not paket:
        await call.message.answer(
            "❌ Paket tidak ditemukan."
        )
        return
    # Semua pembelian VIP/VVIP langsung memakai QR manual.
    return await vip_manual(call, paket_id_override=paket_id)
# ============================================================
# EXTEND VIP
# ============================================================
@router.callback_query(
    F.data.startswith("extendvip:")
)
async def extend_vip(
    call: CallbackQuery,
):
    # ACK FIRST
    await safe_callback_answer(call)
    parts = call.data.split(
        ":",
        1,
    )
    if len(parts) != 2:
        return
    paket_id = parts[1].strip()
    paket = VIP_PACKAGES.get(
        paket_id
    )
    if not paket:
        await call.message.answer(
            "❌ Paket tidak ditemukan."
        )
        return
    # Perpanjangan VIP/VVIP juga langsung memakai QR manual.
    return await vip_manual(call, paket_id_override=paket_id)
# ============================================================
# MANUAL FALLBACK
# ============================================================
async def _manual_fallback(
    call: CallbackQuery,
    paket_id: str,
    paket: dict,
    why: str,
):
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📷 QR Manual",
                    callback_data=(
                        f"vipmanual:{paket_id}"
                    ),
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔙 Kembali",
                    callback_data="vvip",
                )
            ],
        ]
    )
    await call.message.answer(
        (
            "⚠️ <b>QR OTOMATIS ERROR</b>\n\n"
            f"{safe_html(why)}\n\n"
            "Silakan gunakan "
            "<b>QR Manual</b> untuk "
            "melanjutkan pembayaran."
        ),
        parse_mode="HTML",
        reply_markup=kb,
    )
# ============================================================
# OPEN MANUAL PAYMENT
# ============================================================
@router.callback_query(
    F.data.startswith("vipmanual:")
)
async def vip_manual(
    call: CallbackQuery,
    paket_id_override: str | None = None,
):
    # ACK FIRST
    await safe_callback_answer(call)
    parts = call.data.split(
        ":",
        1,
    )
    if len(parts) != 2:
        return
    paket_id = parts[1].strip()
    paket = VIP_PACKAGES.get(
        paket_id
    )
    if not paket:
        await call.message.answer(
            "❌ Paket tidak ditemukan."
        )
        return
    pool = await get_pool()
    user_id = call.from_user.id
    # --------------------------------------------------------
    # CHECK PENDING MANUAL PAYMENT
    # --------------------------------------------------------
    try:
        pending = await pool.fetchrow(
            """
            SELECT id
            FROM vip_manual_payments
            WHERE user_id = $1
              AND status = 'pending'
            ORDER BY id DESC
            LIMIT 1
            """,
            user_id,
        )
    except Exception:
        logger.exception(
            "VIP MANUAL PENDING CHECK ERROR"
        )
        await call.message.answer(
            "❌ Gagal memeriksa "
            "pembayaran manual."
        )
        return
    if pending:
        await call.message.answer(
            "⏳ Kamu masih punya "
            "pembayaran manual yang "
            "menunggu verifikasi."
        )
        return
    # --------------------------------------------------------
    # CREATE MANUAL PAYMENT
    # --------------------------------------------------------
    try:
        tx = await pool.fetchrow(
            """
            INSERT INTO vip_manual_payments
            (
                user_id,
                package_id,
                amount,
                status
            )
            VALUES
            (
                $1,
                $2,
                $3,
                'pending'
            )
            RETURNING id
            """,
            user_id,
            paket_id,
            paket["price"],
        )
    except Exception:
        logger.exception(
            "VIP MANUAL PAYMENT INSERT ERROR"
        )
        await call.message.answer(
            "❌ Gagal membuat "
            "pembayaran manual."
        )
        return
    if not tx:
        await call.message.answer(
            "❌ Pembayaran manual "
            "gagal dibuat."
        )
        return
    tx_id = tx["id"]
    caption = (
        "<b>📷 QR MANUAL VIP</b>\n"
        "━━━━━━━━━━━━━━\n\n"
        f"📦 Paket: "
        f"<b>{safe_html(paket['name'])}</b>\n"
        f"💰 Nominal: "
        f"<b>{rupiah(paket['price'])}</b>\n"
        f"🧾 ID Pembayaran: "
        f"<code>VIPM-{tx_id}</code>\n\n"
        "1. Scan QR manual.\n"
        "2. Bayar <b>sesuai nominal</b>.\n"
        "3. Tekan "
        "<b>✅ Saya Sudah Bayar</b>.\n\n"
        "⚠️ Jika pembayaran belum "
        "lunas/belum masuk, admin dapat "
        "menandai <b>FAILED</b> dan "
        "meminta keterangan."
    )
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Saya Sudah Bayar",
                    callback_data=(
                        f"vipmanualcheck:{tx_id}"
                    ),
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔙 Kembali",
                    callback_data="vvip",
                )
            ],
        ]
    )
    await safe_delete_message(
        call.message
    )
    try:
        await call.message.answer_photo(
            MANUAL_QR_FILE_ID,
            caption=caption,
            parse_mode="HTML",
            reply_markup=kb,
        )
    except Exception:
        logger.exception(
            "VIP MANUAL QR SEND ERROR"
        )
        await call.message.answer(
            (
                "❌ QR Manual tidak dapat "
                "ditampilkan.\n\n"
                f"ID pembayaran: "
                f"<code>VIPM-{tx_id}</code>"
            ),
            parse_mode="HTML",
        )
# ============================================================
# USER CONFIRMS MANUAL PAYMENT
# ============================================================
@router.callback_query(
    F.data.startswith("vipmanualcheck:")
)
async def vip_manual_check(
    call: CallbackQuery,
):
    # ACK FIRST
    await safe_callback_answer(call)
    parts = call.data.split(
        ":",
        1,
    )
    if len(parts) != 2:
        return
    tx_id = parse_int(
        parts[1]
    )
    if tx_id is None:
        await call.message.answer(
            "❌ ID pembayaran tidak valid."
        )
        return
    pool = await get_pool()
    user_id = call.from_user.id
    try:
        tx = await pool.fetchrow(
            """
            SELECT *
            FROM vip_manual_payments
            WHERE id = $1
              AND user_id = $2
              AND status = 'pending'
            """,
            tx_id,
            user_id,
        )
    except Exception:
        logger.exception(
            "VIP MANUAL CHECK DB ERROR"
        )
        await call.message.answer(
            "❌ Gagal memeriksa "
            "pembayaran."
        )
        return
    if not tx:
        await call.message.answer(
            "❌ Transaksi tidak ditemukan "
            "atau sudah diproses."
        )
        return
    paket = VIP_PACKAGES.get(
        tx["package_id"],
        {},
    )
    admin_text = (
        "📥 <b>VIP MANUAL PAYMENT</b>\n"
        "━━━━━━━━━━━━━━\n\n"
        f"👤 User: "
        f"<code>{tx['user_id']}</code>\n"
        f"📦 Paket: "
        f"<b>{safe_html(paket.get('name', tx['package_id']))}</b>\n"
        f"💰 Nominal: "
        f"<b>{rupiah(tx['amount'])}</b>\n"
        f"🧾 ID: "
        f"<code>VIPM-{tx['id']}</code>\n\n"
        "Pilih status setelah "
        "mengecek pembayaran:"
    )
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ APPROVE",
                    callback_data=(
                        f"vipapprove:{tx['id']}"
                    ),
                ),
                InlineKeyboardButton(
                    text="❌ FAILED",
                    callback_data=(
                        f"vipfailed:{tx['id']}"
                    ),
                ),
            ]
        ]
    )
    sent = 0
    # ACK sudah dilakukan sebelum loop admin.
    for admin in ADMIN_IDS:
        try:
            await call.bot.send_message(
                admin,
                admin_text,
                parse_mode="HTML",
                reply_markup=kb,
            )
            sent += 1
        except (
            TelegramBadRequest,
            TelegramForbiddenError,
        ):
            logger.warning(
                "VIP admin notification failed: %s",
                admin,
            )
        except Exception:
            logger.exception(
                "VIP ADMIN NOTIFY ERROR admin=%s",
                admin,
            )
    if sent:
        await call.message.answer(
            "✅ Permintaan verifikasi "
            "sudah dikirim ke admin.\n\n"
            "Tunggu hasil verifikasi."
        )
    else:
        await call.message.answer(
            "❌ Admin tidak dapat "
            "menerima notifikasi."
        )
# ============================================================
# ACTIVATE VIP
# ============================================================
async def _activate_vip(
    pool,
    user_id: int,
    paket: dict,
):
    now = datetime.now()
    package_type = str(
        paket.get(
            "type",
            "vip",
        )
    ).lower()
    if package_type == "vvip":
        field = "vvip_expired"
    else:
        field = "vip_expired"
    old = await pool.fetchval(
        f"""
        SELECT {field}
        FROM users
        WHERE user_id = $1
        """,
        user_id,
    )
    if old and old > now:
        base = old
    else:
        base = now
    expiry = (
        base
        + timedelta(
            days=int(
                paket["days"]
            )
        )
    )
    if package_type == "vvip":
        await pool.execute(
            """
            UPDATE users
            SET
                vvip = TRUE,
                is_vvip = TRUE,
                vvip_expired = $1,
                vip = TRUE,
                is_vip = TRUE,
                vip_expired = $1
            WHERE user_id = $2
            """,
            expiry,
            user_id,
        )
        return expiry, "VVIP"
    await pool.execute(
        """
        UPDATE users
        SET
            vip = TRUE,
            is_vip = TRUE,
            vip_expired = $1
        WHERE user_id = $2
        """,
        expiry,
        user_id,
    )
    return expiry, "VIP"
# ============================================================
# ADMIN APPROVE
# ============================================================
@router.callback_query(
    F.data.startswith("vipapprove:")
)
async def vip_approve(
    call: CallbackQuery,
):
    # ACK FIRST
    await safe_callback_answer(call)
    if call.from_user.id not in ADMIN_IDS:
        if call.message:
            await call.message.answer(
                "❌ Bukan admin."
            )
        return
    parts = call.data.split(
        ":",
        1,
    )
    if len(parts) != 2:
        return
    tx_id = parse_int(
        parts[1]
    )
    if tx_id is None:
        await call.message.answer(
            "❌ ID pembayaran tidak valid."
        )
        return
    pool = await get_pool()
    # --------------------------------------------------------
    # FETCH TRANSACTION
    # --------------------------------------------------------
    try:
        tx = await pool.fetchrow(
            """
            SELECT *
            FROM vip_manual_payments
            WHERE id = $1
              AND status = 'pending'
            """,
            tx_id,
        )
    except Exception:
        logger.exception(
            "VIP APPROVE FETCH ERROR"
        )
        await call.message.answer(
            "❌ Gagal mengambil "
            "data pembayaran."
        )
        return
    if not tx:
        await call.message.answer(
            "❌ Transaksi sudah diproses "
            "atau tidak ditemukan."
        )
        return
    paket = VIP_PACKAGES.get(
        tx["package_id"]
    )
    if not paket:
        await call.message.answer(
            "❌ Paket tidak ditemukan."
        )
        return
    # --------------------------------------------------------
    # ATOMIC APPROVE
    # --------------------------------------------------------
    try:
        updated = await pool.fetchrow(
            """
            UPDATE vip_manual_payments
            SET
                status = 'approved',
                admin_id = $1,
                reviewed_at = NOW()
            WHERE id = $2
              AND status = 'pending'
            RETURNING *
            """,
            call.from_user.id,
            tx_id,
        )
    except Exception:
        logger.exception(
            "VIP APPROVE UPDATE ERROR"
        )
        await call.message.answer(
            "❌ Gagal memproses "
            "approval."
        )
        return
    if not updated:
        await call.message.answer(
            "❌ Transaksi sudah "
            "diproses oleh admin lain."
        )
        return
    # --------------------------------------------------------
    # ACTIVATE
    # --------------------------------------------------------
    try:
        expiry, tier = await _activate_vip(
            pool,
            tx["user_id"],
            paket,
        )
    except Exception:
        logger.exception(
            "VIP ACTIVATE ERROR tx=%s",
            tx_id,
        )
        # Jangan mengubah status approved
        # menjadi failed secara otomatis.
        # Admin harus tahu ada masalah DB.
        await call.message.answer(
            "⚠️ Pembayaran sudah APPROVED, "
            "tetapi aktivasi VIP mengalami "
            "error database.\n\n"
            f"User: <code>{tx['user_id']}</code>\n"
            f"Transaksi: <code>VIPM-{tx_id}</code>",
            parse_mode="HTML",
        )
        return
    # --------------------------------------------------------
    # USER NOTIFICATION
    # --------------------------------------------------------
    try:
        await call.bot.send_message(
            tx["user_id"],
            (
                f"🎉 <b>{safe_html(tier)} "
                "SUDAH AKTIF!</b>\n\n"
                f"📦 Paket: "
                f"<b>{safe_html(paket['name'])}</b>\n"
                f"⏳ Aktif sampai: "
                f"<b>{expiry:%d-%m-%Y %H:%M}</b>\n\n"
                "Terima kasih. Selamat "
                "menikmati akses premium!"
            ),
            parse_mode="HTML",
        )
    except Exception:
        logger.exception(
            "VIP APPROVE USER NOTIFY ERROR"
        )
    # --------------------------------------------------------
    # UPDATE ADMIN MESSAGE
    # --------------------------------------------------------
    try:
        await call.message.edit_text(
            (
                "✅ <b>VIP PAYMENT APPROVED</b>\n\n"
                f"User: "
                f"<code>{tx['user_id']}</code>\n"
                f"Paket: "
                f"<b>{safe_html(paket['name'])}</b>\n"
                f"Sampai: "
                f"<b>{expiry:%d-%m-%Y %H:%M}</b>"
            ),
            parse_mode="HTML",
        )
    except TelegramBadRequest as exc:
        logger.debug(
            "VIP admin message already edited: %s",
            exc,
        )
    except Exception:
        logger.exception(
            "VIP APPROVE ADMIN MESSAGE ERROR"
        )
# ============================================================
# ADMIN FAILED
# ============================================================
@router.callback_query(
    F.data.startswith("vipfailed:")
)
async def vip_failed(
    call: CallbackQuery,
    state: FSMContext,
):
    # ACK FIRST
    await safe_callback_answer(call)
    if call.from_user.id not in ADMIN_IDS:
        await call.message.answer(
            "❌ Bukan admin."
        )
        return
    parts = call.data.split(
        ":",
        1,
    )
    if len(parts) != 2:
        return
    tx_id = parse_int(
        parts[1]
    )
    if tx_id is None:
        await call.message.answer(
            "❌ ID pembayaran tidak valid."
        )
        return
    pool = await get_pool()
    try:
        tx = await pool.fetchrow(
            """
            SELECT *
            FROM vip_manual_payments
            WHERE id = $1
              AND status = 'pending'
            """,
            tx_id,
        )
    except Exception:
        logger.exception(
            "VIP FAILED FETCH ERROR"
        )
        await call.message.answer(
            "❌ Gagal mengambil "
            "data pembayaran."
        )
        return
    if not tx:
        await call.message.answer(
            "❌ Transaksi sudah diproses "
            "atau tidak ditemukan."
        )
        return
    await state.update_data(
        vip_failed_tx=tx_id
    )
    await state.set_state(
        VipManualState.waiting_reason
    )
    await call.message.answer(
        "📝 <b>Masukkan alasan FAILED</b>\n\n"
        "Contoh:\n"
        "<i>Pembayaran belum lunas / "
        "nominal tidak sesuai / "
        "pembayaran belum masuk.</i>\n\n"
        "Ketik alasan yang akan dikirim "
        "ke user.",
        parse_mode="HTML",
    )
# ============================================================
# ADMIN FAILED REASON
# ============================================================
@router.message(
    VipManualState.waiting_reason
)
async def vip_failed_reason(
    message: Message,
    state: FSMContext,
):
    if message.from_user.id not in ADMIN_IDS:
        await state.clear()
        return
    data = await state.get_data()
    tx_id = data.get(
        "vip_failed_tx"
    )
    if not tx_id:
        await state.clear()
        await message.answer(
            "❌ Sesi FAILED tidak ditemukan."
        )
        return
    reason = (
        message.text.strip()
        if message.text
        else "Pembayaran belum terverifikasi."
    )
    if not reason:
        reason = (
            "Pembayaran belum "
            "terverifikasi."
        )
    pool = await get_pool()
    try:
        tx = await pool.fetchrow(
            """
            SELECT *
            FROM vip_manual_payments
            WHERE id = $1
              AND status = 'pending'
            """,
            tx_id,
        )
    except Exception:
        logger.exception(
            "VIP FAILED FETCH ERROR"
        )
        await state.clear()
        await message.answer(
            "❌ Gagal mengambil "
            "data pembayaran."
        )
        return
    if not tx:
        await state.clear()
        await message.answer(
            "❌ Transaksi sudah diproses "
            "atau tidak ditemukan."
        )
        return
    try:
        updated = await pool.fetchrow(
            """
            UPDATE vip_manual_payments
            SET
                status = 'failed',
                reason = $1,
                admin_id = $2,
                reviewed_at = NOW()
            WHERE id = $3
              AND status = 'pending'
            RETURNING *
            """,
            reason,
            message.from_user.id,
            tx_id,
        )
    except Exception:
        logger.exception(
            "VIP FAILED UPDATE ERROR"
        )
        await state.clear()
        await message.answer(
            "❌ Gagal menyimpan "
            "status FAILED."
        )
        return
    if not updated:
        await state.clear()
        await message.answer(
            "❌ Transaksi sudah "
            "diproses oleh admin lain."
        )
        return
    await message.answer(
        (
            "❌ <b>FAILED</b> berhasil disimpan.\n\n"
            "User akan menerima alasan:\n"
            f"<i>{safe_html(reason)}</i>"
        ),
        parse_mode="HTML",
    )
    # --------------------------------------------------------
    # USER NOTIFICATION
    # --------------------------------------------------------
    try:
        await message.bot.send_message(
            tx["user_id"],
            (
                "❌ <b>Pembayaran VIP "
                "belum dapat diverifikasi</b>\n\n"
                f"📝 Masukan admin: "
                f"<i>{safe_html(reason)}</i>\n\n"
                "Jika pembayaran belum "
                "lunas/belum masuk, silakan "
                "lakukan pembayaran yang benar "
                "lalu gunakan QR Manual lagi."
            ),
            parse_mode="HTML",
        )
    except Exception:
        logger.exception(
            "VIP FAILED USER NOTIFY ERROR"
        )
    await state.clear()
# ============================================================
# CHECK AUTO PAYMENT
# ============================================================
@router.callback_query(
    F.data.startswith("vipwait:")
)
async def vip_wait(
    call: CallbackQuery,
):
    # ACK FIRST
    await safe_callback_answer(call)
    parts = call.data.split(
        ":",
        1,
    )
    if len(parts) != 2:
        return
    invoice = parts[1].strip()
    if not invoice:
        await call.message.answer(
            "❌ Invoice tidak valid."
        )
        return
    pool = await get_pool()
    try:
        tx = await pool.fetchrow(
            """
            SELECT
                status,
                expires_at
            FROM payments
            WHERE invoice_id = $1
            LIMIT 1
            """,
            invoice,
        )
    except Exception:
        logger.exception(
            "VIP WAIT DB ERROR"
        )
        await call.message.answer(
            "❌ Gagal memeriksa "
            "status pembayaran."
        )
        return
    if not tx:
        await call.message.answer(
            "❌ Invoice tidak ditemukan."
        )
        return
    status = str(
        tx["status"] or ""
    ).lower()
    if status == "paid":
        await call.message.answer(
            "✅ Pembayaran berhasil.\n\n"
            "VIP sedang/sudah aktif."
        )
        return
    if status in (
        "failed",
        "expired",
        "cancelled",
    ):
        await call.message.answer(
            "❌ Pembayaran gagal atau "
            "kedaluwarsa.\n\n"
            "Silakan gunakan QR Manual."
        )
        return
    await call.message.answer(
        "⏳ Pembayaran belum diterima.\n\n"
        "Jika QR otomatis error, "
        "gunakan <b>📷 QR Manual</b> "
        "untuk melanjutkan.",
        parse_mode="HTML",
    )
