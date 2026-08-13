import logging
import qrcode

from io import BytesIO

from aiogram import Router, F
from aiogram.types import (
    CallbackQuery,
    BufferedInputFile,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)

from database import fetchrow, execute
from utils.dompetx import DompetX

from .pay import (
    finish_payment,
    CHECK_LOCK,
)

logger = logging.getLogger(__name__)

router = Router()


def dompetx_keyboard(payment_id):

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔄 Cek Pembayaran",
                    callback_data=f"dompetxcheck:{payment_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="❌ Batalkan",
                    callback_data=f"dompetxcancel:{payment_id}"
                )
            ]
        ]
    )



# ==================================================
# CREATE PAYMENT DOMPETX
# ==================================================

@router.callback_query(F.data.startswith("dompetx:"))
async def create_dompetx(call: CallbackQuery):

    code = call.data.split(":", 1)[1]

    # ==============================
    # AMBIL FILE
    # ==============================

    file = await fetchrow(
        """
        SELECT *
        FROM files
        WHERE code=$1
        """,
        code
    )

    if not file:
        return await call.answer(
            "❌ File tidak ditemukan",
            show_alert=True
        )

    price = int(file["price"] or 0)

    if price <= 0:
        return await call.answer(
            "❌ Harga file tidak valid",
            show_alert=True
        )

    await call.answer(
        "⏳ Membuat QRIS DompetX..."
    )

    # ==============================
    # CREATE PAYMENT
    # ==============================

    payment = await DompetX.create_payment(
        amount=price,
        description=f"File {code}",
        customer_name=call.from_user.full_name
    )

    if not payment:
        return await call.answer(
            "❌ Gagal membuat pembayaran DompetX",
            show_alert=True
        )

    payment_id = payment.get("payment_id")

    if not payment_id:
        logger.error(
            "DOMPETX PAYMENT ID KOSONG: %s",
            payment
        )

        return await call.answer(
            "❌ Payment ID tidak ditemukan",
            show_alert=True
        )

    # ==============================
    # AMBIL QR STRING
    # ==============================

    qr_string = payment.get("qr_string")

    if not qr_string:
        logger.error(
            "DOMPETX QR STRING KOSONG: %s",
            payment
        )

        return await call.answer(
            "❌ QRIS DompetX tidak tersedia",
            show_alert=True
        )

    # ==============================
    # SIMPAN PURCHASE
    # ==============================

    try:

        await execute(
            """
            INSERT INTO file_purchases
            (
                user_id,
                file_code,
                owner_id,
                paid_price,
                payment_id,
                status,
                created_at
            )
            VALUES
            (
                $1,
                $2,
                $3,
                $4,
                $5,
                'pending',
                NOW()
            )
            """,
            call.from_user.id,
            code,
            file["owner_id"],
            price,
            payment_id
        )

    except Exception:

        logger.exception(
            "DOMPETX INSERT PURCHASE ERROR"
        )

        # Coba batalkan payment jika DB gagal
        try:
            await DompetX.cancel_payment(
                payment_id
            )
        except Exception:
            pass

        return await call.answer(
            "❌ Gagal menyimpan transaksi",
            show_alert=True
        )

    # ==============================
    # GENERATE QRIS
    # ==============================

    try:

        qr = qrcode.make(
            qr_string
        )

        buffer = BytesIO()

        qr.save(
            buffer,
            format="PNG"
        )

        buffer.seek(0)

    except Exception:

        logger.exception(
            "DOMPETX QR GENERATE ERROR"
        )

        await execute(
            """
            UPDATE file_purchases
            SET status='cancel'
            WHERE payment_id=$1
            """,
            payment_id
        )

        try:
            await DompetX.cancel_payment(
                payment_id
            )
        except Exception:
            pass

        return await call.answer(
            "❌ Gagal membuat QRIS",
            show_alert=True
        )

    # ==============================
    # SEND QR
    # ==============================

    try:

        msg = await call.message.answer_photo(
            BufferedInputFile(
                buffer.getvalue(),
                filename="dompetx_qris.png"
            ),
            caption=(
                "💳 <b>DOMPETX QRIS</b>\n\n"
                f"📄 File:\n"
                f"<b>{file['title']}</b>\n\n"
                f"🧾 Invoice:\n"
                f"<code>{payment_id}</code>\n\n"
                f"💰 Total:\n"
                f"<b>Rp {price:,}</b>\n\n"
                "📷 Silakan scan QRIS di atas "
                "untuk melakukan pembayaran.\n\n"
                "Setelah pembayaran berhasil, "
                "tekan tombol <b>🔄 Cek Pembayaran</b>."
            ).replace(",", "."),
            parse_mode="HTML",
            reply_markup=dompetx_keyboard(
                payment_id
            )
        )

    except Exception:

        logger.exception(
            "DOMPETX SEND QR ERROR"
        )

        return await call.answer(
            "❌ Gagal mengirim QRIS",
            show_alert=True
        )

    # ==============================
    # SIMPAN MESSAGE ID
    # ==============================

    await execute(
        """
        UPDATE file_purchases
        SET
            qr_message_id=$1,
            qr_chat_id=$2
        WHERE payment_id=$3
        """,
        msg.message_id,
        msg.chat.id,
        payment_id
    )

    logger.info(
        "DOMPETX PAYMENT CREATED | "
        "payment_id=%s | code=%s | amount=%s",
        payment_id,
        code,
        price
    )


# ==================================================
# CHECK PAYMENT
# ==================================================

@router.callback_query(F.data.startswith("dompetxcheck:"))
async def check_dompetx(call: CallbackQuery):

    payment_id = call.data.split(":")[1]

    if payment_id in CHECK_LOCK:
        return await call.answer(
            "⏳ Sedang diproses...",
            show_alert=True
        )

    CHECK_LOCK.add(payment_id)

    try:

        await call.answer(
            "🔄 Mengecek pembayaran..."
        )

        result = await DompetX.check_payment(
            payment_id
        )

        if not result:
            return await call.answer(
                "❌ Gagal mengecek pembayaran",
                show_alert=True
            )

        status = str(
            result.get("status", "")
        ).lower()

        if status != "paid":
            return await call.answer(
                "⏳ Belum dibayar",
                show_alert=True
            )

        purchase = await fetchrow(
            """
            SELECT *
            FROM file_purchases
            WHERE payment_id=$1
            """,
            payment_id
        )

        if not purchase:
            return await call.answer(
                "Data pembayaran tidak ditemukan",
                show_alert=True
            )

        file = await fetchrow(
            """
            SELECT *
            FROM files
            WHERE code=$1
            """,
            purchase["file_code"]
        )

        if not file:
            return await call.answer(
                "File tidak ditemukan",
                show_alert=True
            )

        await finish_payment(
            call.bot,
            purchase,
            file,
            payment_id,
            call.message
        )

    except Exception:
        logger.exception(
            "DOMPETX CHECK ERROR"
        )

        await call.message.answer(
            "❌ Terjadi kesalahan."
        )

    finally:
        CHECK_LOCK.discard(payment_id)


# ==================================================
# CANCEL PAYMENT
# ==================================================

@router.callback_query(F.data.startswith("dompetxcancel:"))
async def cancel_dompetx(call: CallbackQuery):

    payment_id = call.data.split(":")[1]

    payment = await fetchrow(
        """
        SELECT *
        FROM file_purchases
        WHERE payment_id=$1
        """,
        payment_id
    )

    if not payment:
        return await call.answer(
            "Data tidak ditemukan",
            show_alert=True
        )

    if payment["status"] == "paid":
        return await call.answer(
            "Sudah dibayar",
            show_alert=True
        )

    try:
        await DompetX.cancel_payment(
            payment_id
        )
    except Exception:
        logger.exception(
            "DOMPETX CANCEL ERROR"
        )

    await execute(
        """
        UPDATE file_purchases
        SET status='cancel'
        WHERE payment_id=$1
        """,
        payment_id
    )

    try:

        if (
            payment["qr_message_id"]
            and payment["qr_chat_id"]
        ):

            await call.bot.delete_message(
                payment["qr_chat_id"],
                payment["qr_message_id"]
            )

    except Exception:
        pass

    await call.answer(
        "Pembayaran dibatalkan"
    )

    await call.message.answer(
        "❌ Pembayaran dibatalkan."
    )



