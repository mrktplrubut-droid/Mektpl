import qrcode
from io import BytesIO
from datetime import datetime
import pytz

from aiogram import Router,F
from aiogram.types import CallbackQuery,Message,BufferedInputFile
from aiogram.utils.keyboard import InlineKeyboardBuilder

from database import get_pool
from utils.bayargg import BayarGG
from config_vip import VIP_PACKAGES
from utils.safe_edit import safe_edit

wib=pytz.timezone("Asia/Jakarta")
router=Router()

def build_vvip():
    kb=InlineKeyboardBuilder()

    for key,paket in VIP_PACKAGES.items():
        kb.button(
            text=f"💎 {paket['name']} • Rp {paket['price']:,}".replace(",","."),
            callback_data=f"buyvip:{key}"
        )

    kb.button(
        text="🔙 Kembali",
        callback_data="account"
    )
    kb.adjust(1)

    text=(
        "<b><i>💎 PREMIUM ACCESS</i></b>\n"
        "━━━━━━━━━━━━━━\n\n"
        "Pilih paket premium:\n\n"
        "💠 <b>VIP</b>\n"
        "• Akses file premium\n"
        "• Masa aktif sesuai paket\n"
        "• Tidak bisa upload\n"
        "• Tidak bisa forward media\n\n"
        "💎 <b>VVIP</b>\n"
        "• Semua fitur VIP\n"
        "• Bisa upload file\n"
        "• Bisa save media\n"
        "• Semua fitur terbuka\n"
        "• Storage uploader\n\n"
        "━━━━━━━━━━━━━━\n"
        "👇 Pilih paket:"
    )

    return text,kb.as_markup()

async def open_vvip(message:Message):
    text,markup=build_vvip()
    await message.answer(
        text,
        parse_mode="HTML",
        reply_markup=markup
    )

async def safe_edit_vvip(message):
    text,markup=build_vvip()
    await safe_edit(
        message,
        text,
        reply_markup=markup
    )

@router.message(F.text=="💎 Upgrade")
async def vvip_message(message:Message):
    await open_vvip(message)

@router.callback_query(F.data=="vvip")
async def vvip_menu(call:CallbackQuery):
    try:
        await call.answer()
    except:
        pass
    await safe_edit_vvip(call.message)


# =========================
# BUY VIP / VVIP
# =========================

@router.callback_query(lambda c:c.data and c.data.startswith("buyvip:"))
async def extend_vip(call:CallbackQuery):
    print("🔥 BUY VIP:",call.data)

    try:
        await call.answer()
    except:
        pass

    paket_id=call.data.split(":",1)[1]
    paket=VIP_PACKAGES.get(paket_id)

    if not paket:
        return await call.message.answer("❌ Paket tidak ditemukan")

    pool=await get_pool()

    user=await pool.fetchrow(
        """
        SELECT is_vip,is_vvip,vip_expired,vvip_expired
        FROM users
        WHERE user_id=$1
        """,
        call.from_user.id
    )

    if user:
        expired=None
        jenis=""

        if user["is_vvip"] and user["vvip_expired"]:
            expired=user["vvip_expired"]
            jenis="VVIP"
        elif user["is_vip"] and user["vip_expired"]:
            expired=user["vip_expired"]
            jenis="VIP"

        if expired:
            if expired.tzinfo:
                expired=expired.replace(tzinfo=None)

            if expired>datetime.now():
                kb=InlineKeyboardBuilder()

                kb.button(
                    text="✅ Ya, Perpanjang",
                    callback_data=f"extendvip:{paket_id}"
                )
                kb.button(
                    text="❌ Batal",
                    callback_data="vvip"
                )
                kb.adjust(1)

                return await safe_edit(
                    call.message,
                    (
                        "💎 <b>Membership Masih Aktif</b>\n\n"
                        f"Jenis: <b>{jenis}</b>\n"
                        f"Berakhir: <b>{expired.strftime('%d-%m-%Y %H:%M')}</b>\n\n"
                        "Perpanjang sekarang?"
                    ),
                    reply_markup=kb.as_markup()
                )

    pending=await pool.fetchrow(
        """
        SELECT invoice_id
        FROM payments
        WHERE user_id=$1
        AND status='pending'
        AND expires_at > (NOW() AT TIME ZONE 'Asia/Jakarta')
        LIMIT 1
        """,
        call.from_user.id
    )

    if pending:
        return await call.message.answer(
            "⚠️ Masih ada invoice yang belum dibayar."
        )

    await safe_edit(
        call.message,
        "⏳ Membuat invoice pembayaran..."
    )

    try:
        payment=await BayarGG.create_payment(
            amount=paket["price"],
            description=f"{paket['name']} - {paket['days']} Hari",
            customer_name=call.from_user.full_name
        )

    except Exception as e:
        return await safe_edit(
            call.message,
            f"❌ Gagal membuat invoice\n<code>{e}</code>"
        )

    if not payment:
        return await safe_edit(
            call.message,
            "❌ Invoice gagal dibuat"
        )

    invoice_id=payment["invoice_id"]
    payment_url=payment.get("payment_url")
    qr_string=payment.get("qris_string")

    expires_at=None

    if payment.get("expires_at"):
        try:
            expires_at=datetime.strptime(
                payment["expires_at"],
                "%Y-%m-%d %H:%M:%S"
            )
            
        except Exception as e:
            print("EXPIRED ERROR:",e)
            expires_at=None

    try:
        await pool.execute(
            """
            INSERT INTO payments
            (
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
            ($1,$2,$3,$4,'pending','bayargg',$5,$6,$7,$8)
            """,
            call.from_user.id,
            paket_id,
            invoice_id,
            paket["price"],
            invoice_id,
            payment_url,
            expires_at,
            paket.get("type","vip")
        )

    except Exception as e:
        return await safe_edit(
            call.message,
            f"❌ Database Error\n<code>{e}</code>"
        )

    if paket.get("type")=="vvip":
        akses="💎 VVIP\n✅ Bisa upload\n✅ Semua fitur"
    else:
        akses="💠 VIP\n✅ Akses premium\n❌ Tidak bisa upload"

    text=(
        "<b>💎 INVOICE BERHASIL</b>\n"
        "━━━━━━━━━━━━━━\n\n"
        f"📦 Paket: <b>{paket['name']}</b>\n"
        f"💰 Harga: <b>Rp {paket['price']:,}</b>\n\n"
        f"{akses}\n\n"
        f"🧾 Invoice:\n<code>{invoice_id}</code>\n\n"
        "⏳ Status: MENUNGGU PEMBAYARAN\n\n"
        "Scan QRIS di bawah.\n"
        "Aktif otomatis setelah pembayaran berhasil."
    ).replace(",", ".")

    if expires_at:
        text+=(
            f"\n\n⏰ Expired: {expires_at.strftime('%H:%M:%S')}"
        )

    kb=InlineKeyboardBuilder()
    kb.button(
        text="⏳ Menunggu Pembayaran",
        callback_data="waiting_payment"
    )
    kb.button(
        text="🔙 Kembali",
        callback_data="vvip"
    )
    kb.adjust(1)

    try:
        await call.message.delete()
    except:
        pass

    try:
        if qr_string:
            qr=qrcode.make(qr_string)
            buf=BytesIO()
            qr.save(buf,format="PNG")
            buf.seek(0)

            await call.message.answer_photo(
                BufferedInputFile(
                    buf.getvalue(),
                    filename="qris.png"
                ),
                caption=text,
                parse_mode="HTML",
                reply_markup=kb.as_markup()
            )
        else:
            await call.message.answer(
                text,
                parse_mode="HTML",
                reply_markup=kb.as_markup()
            )

    except Exception as e:
        print("QR ERROR:",e)
        await call.message.answer(
            "❌ Gagal membuat QR pembayaran."
        )
        
# =========================
# WAITING PAYMENT
# =========================

@router.callback_query(F.data=="waiting_payment")
async def waiting_payment(call:CallbackQuery):
    pool=await get_pool()

    payment=await pool.fetchrow(
        """
        SELECT invoice_id,status
        FROM payments
        WHERE user_id=$1
        ORDER BY id DESC
        LIMIT 1
        """,
        call.from_user.id
    )

    if not payment:
        return await call.answer(
            "❌ Invoice tidak ditemukan.",
            show_alert=True
        )

    status=payment["status"]

    if status=="paid":
        return await call.answer(
            "✅ Pembayaran berhasil.",
            show_alert=True
        )

    if status=="expired":
        return await call.answer(
            "⌛ Invoice sudah kedaluwarsa.",
            show_alert=True
        )

    await call.answer(
        "⏳ Pembayaran masih menunggu.",
        show_alert=True
    )
