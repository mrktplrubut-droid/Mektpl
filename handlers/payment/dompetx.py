import logging
import qrcode

from io import BytesIO

from aiogram import Router, F
from aiogram.types import (
    CallbackQuery,
    BufferedInputFile,
)

from database import fetchrow, execute
from utils.dompetx import DompetX

logger = logging.getLogger(__name__)

router = Router()


# ==================================================
# CREATE PAYMENT DOMPETX
# ==================================================

@router.callback_query(F.data.startswith("dompetx:"))
async def create_dompetx(call: CallbackQuery):

    code = call.data.split(":")[1]

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
            "File tidak ditemukan",
            show_alert=True
        )

    price = file["price"] or 0

    await call.answer("⏳ Membuat QRIS DompetX...")

    payment = await DompetX.create_payment(
        amount=price,
        description=f"File {code}",
        customer_name=call.from_user.full_name
    )

    if not payment:
        return await call.answer(
            "Gagal membuat pembayaran",
            show_alert=True
        )

    payment_id = payment["payment_id"]

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
            $1,$2,$3,$4,$5,
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

    qr = qrcode.make(payment["qr_url"])

    buffer = BytesIO()

    qr.save(buffer, "PNG")

    buffer.seek(0)

    msg = await call.message.answer_photo(
        BufferedInputFile(
            buffer.getvalue(),
            filename="dompetx.png"
        ),
        caption=(
            "💳 <b>DOMPETX QRIS</b>\n\n"
            f"Invoice:\n<code>{payment_id}</code>\n\n"
            f"Total:\nRp {price:,}\n\n"
            "Silakan scan QR untuk membayar."
        ).replace(",", "."),
        parse_mode="HTML"
    )

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

    from .payment import payment_check_keyboard

    await msg.edit_reply_markup(
        reply_markup=payment_check_keyboard(payment_id)
    )
