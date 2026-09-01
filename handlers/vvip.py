import logging
import qrcode
from io import BytesIO
from datetime import datetime, timedelta

from aiogram import Router, F
from aiogram.types import CallbackQuery, Message, BufferedInputFile, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext

from database import get_pool
from utils.bayargg import BayarGG
from config_vip import VIP_PACKAGES
from config import MANUAL_QR_FILE_ID, ADMIN_IDS
from utils.safe_edit import safe_edit
from utils.user_lang import get_user_language
from states import VipManualState

logger = logging.getLogger(__name__)
router = Router()


def rupiah(value: int) -> str:
    return f"Rp {int(value):,}".replace(",", ".")


def build_vvip(lang="id"):
    kb = InlineKeyboardBuilder()
    for key, paket in VIP_PACKAGES.items():
        kb.button(
            text=f"💎 {paket['name']} • {rupiah(paket['price'])}",
            callback_data=f"buyvip:{key}"
        )
    kb.button(text="🔙 Kembali" if lang == "id" else "🔙 Back", callback_data="account")
    kb.adjust(1)

    if lang == "id":
        text = (
            "<b>💎 PREMIUM ACCESS</b>\n━━━━━━━━━━━━━━\n\n"
            "Pilih paket yang sesuai kebutuhan kamu.\n\n"
            "💠 <b>VIP</b>\n"
            "• Akses fitur premium\n• Tidak bisa upload\n\n"
            "💎 <b>VVIP</b>\n"
            "• Semua fitur VIP\n• Bisa upload & simpan media\n• Fitur premium terbuka\n\n"
            "💳 Pembayaran bisa otomatis atau QR manual."
        )
    else:
        text = (
            "<b>💎 PREMIUM ACCESS</b>\n━━━━━━━━━━━━━━\n\n"
            "Choose the package you need.\n\n"
            "💠 <b>VIP</b>\n• Premium access\n• Upload is not available\n\n"
            "💎 <b>VVIP</b>\n• All VIP features\n• Upload & save media\n• Premium features unlocked\n\n"
            "💳 Payment supports automatic or manual QR."
        )
    return text, kb.as_markup()


async def open_vvip(message: Message):
    lang = await get_user_language(message.from_user.id)
    text, markup = build_vvip(lang)
    await message.answer(text, parse_mode="HTML", reply_markup=markup)


@router.message(F.text == "💎 Upgrade")
async def vvip_message(message: Message):
    await open_vvip(message)


@router.callback_query(F.data == "vvip")
async def vvip_menu(call: CallbackQuery):
    await call.answer()
    await open_vvip(call.message)


async def _create_auto_vip(call: CallbackQuery, paket_id: str, paket: dict):
    pool = await get_pool()
    pending = await pool.fetchrow(
        """SELECT invoice_id FROM payments
           WHERE user_id=$1 AND status='pending'
           AND (expires_at IS NULL OR expires_at > NOW())
           LIMIT 1""",
        call.from_user.id
    )
    if pending:
        return await call.message.answer(
            "⚠️ Masih ada pembayaran VIP yang belum selesai. Selesaikan atau tunggu sampai kedaluwarsa."
        )

    try:
        payment = await BayarGG.create_payment(
            amount=paket["price"],
            description=f"{paket['name']} - {paket['days']} Hari",
            customer_name=call.from_user.full_name
        )
    except Exception:
        logger.exception("VIP AUTO PAYMENT ERROR")
        return await _manual_fallback(call, paket_id, paket, "QR otomatis mengalami gangguan.")

    if not payment:
        return await _manual_fallback(call, paket_id, paket, "Invoice otomatis gagal dibuat.")

    invoice_id = payment.get("invoice_id")
    qr_string = payment.get("qris_string")
    if not invoice_id:
        return await _manual_fallback(call, paket_id, paket, "Invoice otomatis tidak valid.")

    expires_at = None
    raw_exp = payment.get("expires_at")
    if raw_exp:
        try:
            expires_at = datetime.strptime(str(raw_exp), "%Y-%m-%d %H:%M:%S")
        except Exception:
            expires_at = None

    try:
        await pool.execute(
            """INSERT INTO payments
               (order_id,user_id,code,reference,amount,status,provider,invoice_id,payment_url,expires_at,type)
               VALUES($1,$2,$3,$4,$5,'pending','bayargg',$6,$7,$8,$9)
               ON CONFLICT (invoice_id) DO NOTHING""",
            invoice_id, call.from_user.id, paket_id, invoice_id,
            paket["price"], invoice_id, payment.get("payment_url"),
            expires_at, paket.get("type", "vip")
        )
    except Exception:
        logger.exception("VIP PAYMENT DB ERROR")
        return await _manual_fallback(call, paket_id, paket, "Database pembayaran otomatis bermasalah.")

    text = (
        "<b>💳 PEMBAYARAN VIP</b>\n━━━━━━━━━━━━━━\n\n"
        f"📦 Paket: <b>{paket['name']}</b>\n"
        f"💰 Harga: <b>{rupiah(paket['price'])}</b>\n"
        f"🧾 Invoice: <code>{invoice_id}</code>\n\n"
        "📷 Scan QR otomatis untuk membayar.\n"
        "⚠️ Jika QR otomatis error/tidak bisa dipakai, tekan <b>📷 QR Manual</b>.\n\n"
        "Setelah pembayaran berhasil, VIP akan aktif otomatis."
    )
    kb = InlineKeyboardBuilder()
    kb.button(text="⏳ Cek Pembayaran", callback_data=f"vipwait:{invoice_id}")
    kb.button(text="📷 QR Manual", callback_data=f"vipmanual:{paket_id}")
    kb.button(text="❌ Batal", callback_data="vvip")
    kb.adjust(1)

    try:
        await call.message.delete()
    except Exception:
        pass

    if qr_string:
        try:
            qr = qrcode.make(qr_string)
            buf = BytesIO()
            qr.save(buf, format="PNG")
            buf.seek(0)
            await call.message.answer_photo(
                BufferedInputFile(buf.getvalue(), filename="vip-qris.png"),
                caption=text, parse_mode="HTML", reply_markup=kb.as_markup()
            )
            return
        except Exception:
            logger.exception("VIP QR GENERATION ERROR")

    await call.message.answer(
        text + "\n\n⚠️ <b>QR otomatis tidak tersedia.</b> Gunakan QR Manual di bawah.",
        parse_mode="HTML", reply_markup=kb.as_markup()
    )


@router.callback_query(F.data.startswith("buyvip:"))
async def buy_vip(call: CallbackQuery):
    paket_id = call.data.split(":", 1)[1]
    paket = VIP_PACKAGES.get(paket_id)
    if not paket:
        return await call.answer("❌ Paket tidak ditemukan.", show_alert=True)

    await call.answer()
    await _create_auto_vip(call, paket_id, paket)


@router.callback_query(F.data.startswith("extendvip:"))
async def extend_vip(call: CallbackQuery):
    paket_id = call.data.split(":", 1)[1]
    paket = VIP_PACKAGES.get(paket_id)
    if not paket:
        return await call.answer("❌ Paket tidak ditemukan.", show_alert=True)
    await call.answer()
    await _create_auto_vip(call, paket_id, paket)


async def _manual_fallback(call: CallbackQuery, paket_id: str, paket: dict, why: str):
    await call.message.answer(
        f"⚠️ <b>QR OTOMATIS ERROR</b>\n\n{why}\n"
        "Silakan gunakan <b>QR Manual</b> untuk melanjutkan pembayaran.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="📷 QR Manual", callback_data=f"vipmanual:{paket_id}"),
            InlineKeyboardButton(text="🔙 Kembali", callback_data="vvip")
        ]])
    )


@router.callback_query(F.data.startswith("vipmanual:"))
async def vip_manual(call: CallbackQuery):
    paket_id = call.data.split(":", 1)[1]
    paket = VIP_PACKAGES.get(paket_id)
    if not paket:
        return await call.answer("❌ Paket tidak ditemukan.", show_alert=True)

    pool = await get_pool()
    pending = await pool.fetchrow(
        """SELECT id FROM vip_manual_payments
           WHERE user_id=$1 AND status='pending' ORDER BY id DESC LIMIT 1""",
        call.from_user.id
    )
    if pending:
        return await call.answer("⏳ Kamu masih punya pembayaran manual yang menunggu verifikasi.", show_alert=True)

    tx = await pool.fetchrow(
        """INSERT INTO vip_manual_payments(user_id,package_id,amount,status)
           VALUES($1,$2,$3,'pending') RETURNING id""",
        call.from_user.id, paket_id, paket["price"]
    )

    caption = (
        "<b>📷 QR MANUAL VIP</b>\n━━━━━━━━━━━━━━\n\n"
        f"📦 Paket: <b>{paket['name']}</b>\n"
        f"💰 Nominal: <b>{rupiah(paket['price'])}</b>\n"
        f"🧾 ID Pembayaran: <code>VIPM-{tx['id']}</code>\n\n"
        "1. Scan QR manual.\n"
        "2. Bayar <b>sesuai nominal</b>.\n"
        "3. Tekan <b>✅ Saya Sudah Bayar</b>.\n\n"
        "⚠️ Jika pembayaran belum lunas/belum masuk, admin dapat menandai <b>FAILED</b> dan meminta keterangan."
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Saya Sudah Bayar", callback_data=f"vipmanualcheck:{tx['id']}")],
        [InlineKeyboardButton(text="🔙 Kembali", callback_data="vvip")]
    ])
    try:
        await call.message.delete()
    except Exception:
        pass
    await call.message.answer_photo(MANUAL_QR_FILE_ID, caption=caption, parse_mode="HTML", reply_markup=kb)
    await call.answer()


@router.callback_query(F.data.startswith("vipmanualcheck:"))
async def vip_manual_check(call: CallbackQuery):
    tx_id = int(call.data.split(":", 1)[1])
    pool = await get_pool()
    tx = await pool.fetchrow(
        """SELECT * FROM vip_manual_payments
           WHERE id=$1 AND user_id=$2 AND status='pending'""",
        tx_id, call.from_user.id
    )
    if not tx:
        return await call.answer("❌ Transaksi tidak ditemukan atau sudah diproses.", show_alert=True)

    paket = VIP_PACKAGES.get(tx["package_id"], {})
    admin_text = (
        "📥 <b>VIP MANUAL PAYMENT</b>\n━━━━━━━━━━━━━━\n\n"
        f"👤 User: <code>{tx['user_id']}</code>\n"
        f"📦 Paket: <b>{paket.get('name', tx['package_id'])}</b>\n"
        f"💰 Nominal: <b>{rupiah(tx['amount'])}</b>\n"
        f"🧾 ID: <code>VIPM-{tx['id']}</code>\n\n"
        "Pilih status setelah mengecek pembayaran:"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ APPROVE", callback_data=f"vipapprove:{tx['id']}"),
        InlineKeyboardButton(text="❌ FAILED", callback_data=f"vipfailed:{tx['id']}")
    ]])
    sent = 0
    for admin in ADMIN_IDS:
        try:
            await call.bot.send_message(admin, admin_text, parse_mode="HTML", reply_markup=kb)
            sent += 1
        except Exception:
            logger.exception("VIP ADMIN NOTIFY ERROR admin=%s", admin)
    if sent:
        await call.message.answer("✅ Permintaan verifikasi sudah dikirim ke admin. Tunggu hasil verifikasi.")
        await call.answer("Terkirim.")
    else:
        await call.answer("❌ Admin tidak dapat menerima notifikasi.", show_alert=True)


async def _activate_vip(pool, user_id: int, paket: dict):
    now = datetime.now()
    field = "vvip_expired" if paket.get("type") == "vvip" else "vip_expired"
    old = await pool.fetchval(f"SELECT {field} FROM users WHERE user_id=$1", user_id)
    base = old if old and old > now else now
    expiry = base + timedelta(days=paket["days"])
    if paket.get("type") == "vvip":
        await pool.execute(
            """UPDATE users SET vvip=TRUE,is_vvip=TRUE,vvip_expired=$1,
               vip=TRUE,is_vip=TRUE,vip_expired=$1 WHERE user_id=$2""",
            expiry, user_id
        )
        return expiry, "VVIP"
    await pool.execute(
        "UPDATE users SET vip=TRUE,is_vip=TRUE,vip_expired=$1 WHERE user_id=$2",
        expiry, user_id
    )
    return expiry, "VIP"


@router.callback_query(F.data.startswith("vipapprove:"))
async def vip_approve(call: CallbackQuery):
    if call.from_user.id not in ADMIN_IDS:
        return await call.answer("❌ Bukan admin.", show_alert=True)
    tx_id = int(call.data.split(":", 1)[1])
    pool = await get_pool()
    tx = await pool.fetchrow(
        "SELECT * FROM vip_manual_payments WHERE id=$1 AND status='pending'", tx_id
    )
    if not tx:
        return await call.answer("❌ Transaksi sudah diproses.", show_alert=True)

    paket = VIP_PACKAGES.get(tx["package_id"])
    if not paket:
        return await call.answer("❌ Paket tidak ditemukan.", show_alert=True)

    updated = await pool.fetchrow(
        """UPDATE vip_manual_payments SET status='approved',admin_id=$1,reviewed_at=NOW()
           WHERE id=$2 AND status='pending' RETURNING *""",
        call.from_user.id, tx_id
    )
    if not updated:
        return await call.answer("❌ Sudah diproses.", show_alert=True)

    expiry, tier = await _activate_vip(pool, tx["user_id"], paket)
    try:
        await call.bot.send_message(
            tx["user_id"],
            f"🎉 <b>{tier} SUDAH AKTIF!</b>\n\n"
            f"📦 Paket: <b>{paket['name']}</b>\n"
            f"⏳ Aktif sampai: <b>{expiry:%d-%m-%Y %H:%M}</b>\n\n"
            "Terima kasih. Selamat menikmati akses premium!",
            parse_mode="HTML"
        )
    except Exception:
        logger.exception("VIP APPROVE USER NOTIFY ERROR")
    await call.message.edit_text(
        f"✅ <b>VIP PAYMENT APPROVED</b>\n\nUser: <code>{tx['user_id']}</code>\n"
        f"Paket: <b>{paket['name']}</b>\nSampai: <b>{expiry:%d-%m-%Y %H:%M}</b>",
        parse_mode="HTML"
    )
    await call.answer("Approved.")


@router.callback_query(F.data.startswith("vipfailed:"))
async def vip_failed(call: CallbackQuery, state: FSMContext):
    if call.from_user.id not in ADMIN_IDS:
        return await call.answer("❌ Bukan admin.", show_alert=True)
    tx_id = int(call.data.split(":", 1)[1])
    pool = await get_pool()
    tx = await pool.fetchrow(
        "SELECT * FROM vip_manual_payments WHERE id=$1 AND status='pending'", tx_id
    )
    if not tx:
        return await call.answer("❌ Transaksi sudah diproses.", show_alert=True)

    await state.update_data(vip_failed_tx=tx_id)
    await state.set_state(VipManualState.waiting_reason)
    await call.message.answer(
        "📝 <b>Masukkan alasan FAILED</b>\n\n"
        "Contoh: <i>Pembayaran belum lunas / nominal tidak sesuai / pembayaran belum masuk.</i>\n\n"
        "Ketik alasan yang akan dikirim ke user.",
        parse_mode="HTML"
    )
    await call.answer()


@router.message(VipManualState.waiting_reason)
async def vip_failed_reason(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        await state.clear()
        return
    data = await state.get_data()
    tx_id = data.get("vip_failed_tx")
    reason = message.text.strip() if message.text else "Pembayaran belum terverifikasi."
    pool = await get_pool()
    tx = await pool.fetchrow(
        "SELECT * FROM vip_manual_payments WHERE id=$1 AND status='pending'", tx_id
    )
    if not tx:
        await state.clear()
        return await message.answer("❌ Transaksi sudah diproses.")

    updated = await pool.fetchrow(
        """UPDATE vip_manual_payments SET status='failed',reason=$1,admin_id=$2,reviewed_at=NOW()
           WHERE id=$3 AND status='pending' RETURNING *""",
        reason, message.from_user.id, tx_id
    )
    if not updated:
        await state.clear()
        return await message.answer("❌ Transaksi sudah diproses.")

    await message.answer(
        f"❌ <b>FAILED</b> dikirim.\nUser akan menerima alasan:\n<i>{reason}</i>",
        parse_mode="HTML"
    )
    try:
        await message.bot.send_message(
            tx["user_id"],
            "❌ <b>Pembayaran VIP belum dapat diverifikasi</b>\n\n"
            f"📝 Masukan admin: <i>{reason}</i>\n\n"
            "Jika pembayaran belum lunas/belum masuk, silakan lakukan pembayaran yang benar lalu gunakan QR Manual lagi.",
            parse_mode="HTML"
        )
    except Exception:
        logger.exception("VIP FAILED USER NOTIFY ERROR")
    await state.clear()


@router.callback_query(F.data.startswith("vipwait:"))
async def vip_wait(call: CallbackQuery):
    invoice = call.data.split(":", 1)[1]
    pool = await get_pool()
    tx = await pool.fetchrow("SELECT status FROM payments WHERE invoice_id=$1", invoice)
    if not tx:
        return await call.answer("❌ Invoice tidak ditemukan.", show_alert=True)
    status = tx["status"]
    if status == "paid":
        return await call.answer("✅ Pembayaran berhasil. VIP sedang/ sudah aktif.", show_alert=True)
    if status in ("failed", "expired"):
        return await call.answer("❌ Pembayaran gagal/kedaluwarsa. Silakan gunakan QR Manual.", show_alert=True)
    await call.answer("⏳ Pembayaran belum diterima. Jika QR otomatis error, gunakan QR Manual.", show_alert=True)
