import logging
import qrcode

from io import BytesIO
from datetime import datetime

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


# ==================================================
# KEYBOARD
# ==================================================

def dompetx_keyboard(payment_id: str):

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
# PARSE DOMPETX DATETIME
# ==================================================

def parse_dompetx_datetime(value):
    """
    DompetX:
    2026-08-15T13:32:18+07:00

    PostgreSQL/asyncpg:
    membutuhkan datetime, bukan string.
    """

    if not value:
        return None

    if isinstance(value, datetime):
        return value

    if isinstance(value, str):

        try:
            return datetime.fromisoformat(
                value.replace("Z", "+00:00")
            )

        except ValueError:

            logger.warning(
                "DOMPETX INVALID DATETIME: %s",
                value
            )

            return None

    return None


# ==================================================
# FORMAT RUPIAH
# ==================================================

def format_rupiah(amount):

    try:
        return f"Rp {int(amount):,}".replace(",", ".")
    except Exception:
        return f"Rp {amount}"


# ==================================================
# GENERATE QR
# ==================================================

def generate_qr(qr_string):

    qr = qrcode.make(qr_string)

    buffer = BytesIO()

    qr.save(
        buffer,
        format="PNG"
    )

    buffer.seek(0)

    return buffer.getvalue()


# ==================================================
# CREATE PAYMENT DOMPETX
# ==================================================

@router.callback_query(F.data.startswith("dompetx:"))
async def create_dompetx(call: CallbackQuery):

    code = call.data.split(":", 1)[1]
    user_id = call.from_user.id

    # ==================================================
    # AMBIL FILE
    # ==================================================

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
            "❌ File tidak ditemukan.",
            show_alert=True
        )

    price = int(
        file["price"] or 0
    )

    if price <= 0:

        return await call.answer(
            "❌ Harga file tidak valid.",
            show_alert=True
        )

    # ==================================================
    # CEK PURCHASE USER + FILE
    # ==================================================

    existing = await fetchrow(
        """
        SELECT *
        FROM file_purchases
        WHERE user_id=$1
          AND file_code=$2
        ORDER BY created_at DESC
        LIMIT 1
        """,
        user_id,
        code
    )

    # ==================================================
    # SUDAH BAYAR
    # ==================================================

    if existing:

        existing_status = str(
            existing["status"] or ""
        ).lower()

        if existing_status == "paid":

            return await call.answer(
                "✅ File ini sudah kamu beli.",
                show_alert=True
            )

    # ==================================================
    # PAYMENT LAMA PENDING
    # ==================================================

    if existing and str(
        existing["status"] or ""
    ).lower() == "pending":

        old_payment_id = existing["payment_id"]

        if old_payment_id:

            await call.answer(
                "🔄 Mengecek pembayaran sebelumnya..."
            )

            try:

                old_result = await DompetX.check_payment(
                    old_payment_id
                )

            except Exception:

                logger.exception(
                    "DOMPETX CHECK OLD PAYMENT ERROR"
                )

                old_result = None

            # ==================================================
            # HASIL CHECK BERHASIL
            # ==================================================

            if old_result:

                old_status = str(
                    old_result.get("status", "")
                ).lower()

                logger.info(
                    "DOMPETX OLD PAYMENT | "
                    "payment_id=%s | status=%s",
                    old_payment_id,
                    old_status
                )

                # ==================================================
                # SUDAH BAYAR
                # ==================================================

                if old_status in (
                    "paid",
                    "success",
                    "settled",
                    "completed"
                ):

                    await execute(
                        """
                        UPDATE file_purchases
                        SET
                            status='paid',
                            paid_at=NOW()
                        WHERE payment_id=$1
                        """,
                        old_payment_id
                    )

                    purchase = await fetchrow(
                        """
                        SELECT *
                        FROM file_purchases
                        WHERE payment_id=$1
                        """,
                        old_payment_id
                    )

                    if purchase:

                        await finish_payment(
                            call.bot,
                            purchase,
                            file,
                            old_payment_id,
                            call.message
                        )

                    return

                # ==================================================
                # MASIH AKTIF
                # ==================================================

                if old_status in (
                    "pending",
                    "processing",
                    "unpaid",
                    "created"
                ):

                    old_qr_string = existing.get(
                        "qr_string"
                    )

                    if old_qr_string:

                        try:

                            qr_data = generate_qr(
                                old_qr_string
                            )

                            await call.message.answer_photo(
                                BufferedInputFile(
                                    qr_data,
                                    filename="dompetx_qris.png"
                                ),
                                caption=(
                                    "💳 <b>PEMBAYARAN MASIH BERJALAN</b>\n\n"

                                    f"📄 File:\n"
                                    f"<b>{file['title']}</b>\n\n"

                                    f"🧾 Invoice:\n"
                                    f"<code>{old_payment_id}</code>\n\n"

                                    f"💰 Total:\n"
                                    f"<b>{format_rupiah(price)}</b>\n\n"

                                    "📷 Silakan scan QRIS di atas.\n\n"

                                    "Jika sudah membayar, "
                                    "tekan <b>🔄 Cek Pembayaran</b>."
                                ),
                                parse_mode="HTML",
                                reply_markup=dompetx_keyboard(
                                    old_payment_id
                                )
                            )

                            return

                        except Exception:

                            logger.exception(
                                "DOMPETX RESEND OLD QR ERROR"
                            )

                    return await call.answer(
                        "⏳ Pembayaran sebelumnya masih aktif.",
                        show_alert=True
                    )

                # ==================================================
                # EXPIRED / CANCEL / FAILED
                # ==================================================

                if old_status in (
                    "expired",
                    "cancel",
                    "cancelled",
                    "canceled",
                    "failed",
                    "rejected"
                ):

                    logger.info(
                        "DOMPETX OLD PAYMENT CLOSED | "
                        "payment_id=%s | status=%s",
                        old_payment_id,
                        old_status
                    )

                    await execute(
                        """
                        UPDATE file_purchases
                        SET status=$1
                        WHERE payment_id=$2
                        """,
                        old_status,
                        old_payment_id
                    )

                # ==================================================
                # UNKNOWN
                # ==================================================

                else:

                    logger.warning(
                        "DOMPETX UNKNOWN STATUS | "
                        "payment_id=%s | status=%s",
                        old_payment_id,
                        old_status
                    )

                    return await call.answer(
                        f"⏳ Status pembayaran: {old_status}",
                        show_alert=True
                    )

    # ==================================================
    # BUAT PAYMENT BARU
    # ==================================================

    await call.answer(
        "⏳ Membuat QRIS DompetX..."
    )

    payment = await DompetX.create_payment(
        amount=price,
        description=f"File {code}",
        customer_name=call.from_user.full_name
    )

    if not payment:

        return await call.answer(
            "❌ Gagal membuat pembayaran DompetX.",
            show_alert=True
        )

    payment_id = payment.get(
        "payment_id"
    )

    if not payment_id:

        logger.error(
            "DOMPETX PAYMENT ID KOSONG: %s",
            payment
        )

        return await call.answer(
            "❌ Payment ID tidak ditemukan.",
            show_alert=True
        )

    # ==================================================
    # QR STRING
    # ==================================================

    qr_string = payment.get(
        "qr_string"
    )

    if not qr_string:

        logger.error(
            "DOMPETX QR STRING KOSONG: %s",
            payment
        )

        try:
            await DompetX.cancel_payment(
                payment_id
            )
        except Exception:
            pass

        return await call.answer(
            "❌ QRIS DompetX tidak tersedia.",
            show_alert=True
        )

    # ==================================================
    # PARSE EXPIRES AT
    # ==================================================

    expires_at = parse_dompetx_datetime(
        payment.get("expires_at")
    )

    # ==================================================
    # QR IMAGE
    # ==================================================

    qr_image = payment.get(
        "qr_image"
    )

    payment_url = payment.get(
        "payment_url"
    )

    # ==================================================
    # SIMPAN PAYMENT
    # ==================================================

    try:

        if existing:

            await execute(
                """
                UPDATE file_purchases
                SET
                    owner_id=$1,
                    paid_price=$2,
                    payment_id=$3,
                    status='pending',
                    qr_string=$4,
                    qr_image=$5,
                    payment_url=$6,
                    expires_at=$7,
                    qr_message_id=NULL,
                    qr_chat_id=NULL,
                    paid_at=NULL,
                    created_at=NOW()
                WHERE user_id=$8
                  AND file_code=$9
                """,
                file["owner_id"],
                price,
                payment_id,
                qr_string,
                qr_image,
                payment_url,
                expires_at,
                user_id,
                code
            )

        else:

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
                    qr_string,
                    qr_image,
                    payment_url,
                    expires_at,
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
                    $6,
                    $7,
                    $8,
                    $9,
                    NOW()
                )
                """,
                user_id,
                code,
                file["owner_id"],
                price,
                payment_id,
                qr_string,
                qr_image,
                payment_url,
                expires_at
            )

    except Exception:

        logger.exception(
            "DOMPETX SAVE PURCHASE ERROR"
        )

        try:
            await DompetX.cancel_payment(
                payment_id
            )
        except Exception:
            pass

        return await call.answer(
            "❌ Gagal menyimpan transaksi.",
            show_alert=True
        )

    # ==================================================
    # GENERATE QR
    # ==================================================

    try:

        qr_data = generate_qr(
            qr_string
        )

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
            "❌ Gagal membuat QRIS.",
            show_alert=True
        )

    # ==================================================
    # CAPTION
    # ==================================================

    caption = (
        "💳 <b>OO File Bot</b>\n\n"
        f"📄 File:\n"
        f"<b>{file['title']}</b>\n\n"
        f"🧾 Invoice:\n"
        f"<code>{payment_id}</code>\n\n"
        f"💰 Total:\n"
        f"<b>{format_rupiah(price)}</b>\n\n"

        "📷 Silakan scan QRIS di atas "
        "untuk melakukan pembayaran.\n\n"

        "Setelah pembayaran berhasil, "
        "tekan tombol <b>🔄 Cek Pembayaran</b>."
    )

    if expires_at:

        caption += (
            "\n\n⏰ Expired:\n"
            f"<code>{expires_at.strftime('%d-%m-%Y %H:%M:%S %z')}</code>"
        )

    # ==================================================
    # KIRIM QR
    # ==================================================

    try:

        msg = await call.message.answer_photo(
            BufferedInputFile(
                qr_data,
                filename="dompetx_qris.png"
            ),
            caption=caption,
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
            "❌ Gagal mengirim QRIS.",
            show_alert=True
        )

    # ==================================================
    # SIMPAN MESSAGE ID
    # ==================================================

    try:

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

    except Exception:

        logger.exception(
            "DOMPETX SAVE QR MESSAGE ERROR"
        )

    # ==================================================
    # LOG
    # ==================================================

    logger.info(
        "DOMPETX PAYMENT CREATED | "
        "payment_id=%s | user=%s | code=%s | amount=%s | expires=%s",
        payment_id,
        user_id,
        code,
        price,
        expires_at
    )


# ==================================================
# CHECK PAYMENT
# ==================================================

@router.callback_query(
    F.data.startswith("dompetxcheck:")
)
async def check_dompetx(call: CallbackQuery):

    payment_id = call.data.split(
        ":", 1
    )[1]

    if payment_id in CHECK_LOCK:

        return await call.answer(
            "⏳ Sedang diproses...",
            show_alert=True
        )

    CHECK_LOCK.add(
        payment_id
    )

    try:

        await call.answer(
            "🔄 Mengecek pembayaran..."
        )

        result = await DompetX.check_payment(
            payment_id
        )

        if not result:

            return await call.answer(
                "❌ Gagal mengecek pembayaran.",
                show_alert=True
            )

        status = str(
            result.get("status", "")
        ).lower()

        logger.info(
            "DOMPETX MANUAL CHECK | "
            "payment_id=%s | status=%s",
            payment_id,
            status
        )

        # ==================================================
        # BELUM BAYAR
        # ==================================================

        if status not in (
            "paid",
            "success",
            "settled",
            "completed"
        ):

            if status in (
                "expired",
                "cancel",
                "cancelled",
                "canceled",
                "failed",
                "rejected"
            ):

                await execute(
                    """
                    UPDATE file_purchases
                    SET status=$1
                    WHERE payment_id=$2
                    """,
                    status,
                    payment_id
                )

                return await call.answer(
                    f"❌ Pembayaran {status}.",
                    show_alert=True
                )

            return await call.answer(
                "⏳ Pembayaran belum diterima.",
                show_alert=True
            )

        # ==================================================
        # AMBIL PURCHASE
        # ==================================================

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
                "❌ Data pembayaran tidak ditemukan.",
                show_alert=True
            )

        # ==================================================
        # CEGAH DOUBLE FINISH
        # ==================================================

        if str(
            purchase["status"] or ""
        ).lower() == "paid":

            return await call.answer(
                "✅ Pembayaran sudah diproses.",
                show_alert=True
            )

        # ==================================================
        # FILE
        # ==================================================

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
                "❌ File tidak ditemukan.",
                show_alert=True
            )

        # ==================================================
        # UPDATE PAID
        # ==================================================

        await execute(
            """
            UPDATE file_purchases
            SET
                status='paid',
                paid_at=NOW()
            WHERE payment_id=$1
              AND status='pending'
            """,
            payment_id
        )

        # ==================================================
        # FINISH
        # ==================================================

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

        try:
            await call.message.answer(
                "❌ Terjadi kesalahan saat memproses pembayaran."
            )
        except Exception:
            pass

    finally:

        CHECK_LOCK.discard(
            payment_id
        )


# ==================================================
# CANCEL PAYMENT
# ==================================================

@router.callback_query(
    F.data.startswith("dompetxcancel:")
)
async def cancel_dompetx(call: CallbackQuery):

    payment_id = call.data.split(
        ":",
        1
    )[1]

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
            "❌ Data pembayaran tidak ditemukan.",
            show_alert=True
        )

    status = str(
        payment["status"] or ""
    ).lower()

    if status == "paid":

        return await call.answer(
            "❌ Pembayaran sudah dibayar.",
            show_alert=True
        )

    # ==================================================
    # CANCEL PROVIDER
    # ==================================================

    try:

        result = await DompetX.cancel_payment(
            payment_id
        )

        logger.info(
            "DOMPETX CANCEL | "
            "payment_id=%s | result=%s",
            payment_id,
            result
        )

    except Exception:

        logger.exception(
            "DOMPETX CANCEL ERROR"
        )

    # ==================================================
    # UPDATE DATABASE
    # ==================================================

    await execute(
        """
        UPDATE file_purchases
        SET status='cancel'
        WHERE payment_id=$1
          AND status!='paid'
        """,
        payment_id
    )

    # ==================================================
    # DELETE QR MESSAGE
    # ==================================================

    try:

        if (
            payment["qr_message_id"]
            and payment["qr_chat_id"]
        ):

            await call.bot.delete_message(
                chat_id=payment["qr_chat_id"],
                message_id=payment["qr_message_id"]
            )

    except Exception:

        logger.warning(
            "DOMPETX DELETE QR MESSAGE FAILED",
            exc_info=True
        )

    await call.answer(
        "✅ Pembayaran dibatalkan."
    )

    try:

        await call.message.answer(
            "❌ Pembayaran dibatalkan."
        )

    except Exception:
        pass
