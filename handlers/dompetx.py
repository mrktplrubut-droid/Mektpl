# ============================================================
# handlers/dompetx.py
# DOMPETX FILE PAYMENT HANDLER
# Aiogram 3.x
# ============================================================

import logging
from io import BytesIO
from typing import Any, Optional

import qrcode

from aiogram import F, Router
from aiogram.types import CallbackQuery, BufferedInputFile

from database import fetchrow, execute
from utils.dompetx import DompetX

from .pay import (
    finish_payment,
    CHECK_LOCK,
    SUCCESS_STATUSES,
    FAILED_STATUSES,
    normalize_status,
    format_rupiah,
    payment_check_keyboard,
)


logger = logging.getLogger(__name__)

router = Router()


# ============================================================
# CONSTANTS
# ============================================================

ACTIVE_STATUSES = {
    "pending",
    "processing",
    "unpaid",
    "created",
}

PURCHASE_PENDING = "pending"
PURCHASE_PAID = "paid"
PURCHASE_CANCEL = "cancel"


# ============================================================
# KEYBOARD
# ============================================================

def dompetx_keyboard(payment_id: str):
    """
    Keyboard untuk pembayaran DompetX.
    Fungsi payment_check_keyboard berasal dari pay.py.
    """
    return payment_check_keyboard(
        str(payment_id),
        "dompetx",
    )


# ============================================================
# SAFE VALUE HELPERS
# ============================================================

def safe_int(value: Any, default: int = 0) -> int:
    """
    Convert value ke integer secara aman.
    """
    try:
        if value is None:
            return default

        if isinstance(value, bool):
            return int(value)

        return int(value)

    except (TypeError, ValueError):
        return default


def safe_str(value: Any, default: str = "") -> str:
    """
    Convert value ke string secara aman.
    """
    if value is None:
        return default

    try:
        return str(value).strip()
    except Exception:
        return default


def get_file_title(file: Any) -> str:
    """
    Ambil title file tanpa menyebabkan KeyError.
    """
    try:
        title = file.get("title")
    except Exception:
        title = None

    return safe_str(
        title,
        "File",
    )


# ============================================================
# GENERATE QR
# ============================================================

def generate_qr(qr_string: str) -> bytes:
    """
    Generate QR PNG dari QRIS string.
    """

    qr_string = safe_str(qr_string)

    if not qr_string:
        raise ValueError(
            "QR string kosong"
        )

    qr = qrcode.make(
        qr_string
    )

    buffer = BytesIO()

    qr.save(
        buffer,
        format="PNG",
    )

    buffer.seek(0)

    return buffer.getvalue()


# ============================================================
# GET PURCHASE
# ============================================================

async def get_dompetx_purchase(
    payment_id: str,
):
    """
    Ambil transaksi berdasarkan payment_id.
    """

    payment_id = safe_str(payment_id)

    if not payment_id:
        return None

    return await fetchrow(
        """
        SELECT
            id,
            user_id,
            file_code,
            created_at,
            owner_id,
            paid_price,
            payment_id,
            status,
            qr_message_id,
            qr_chat_id,
            paid_at,
            qr_string,
            qr_image,
            payment_url,
            expires_at,
            code
        FROM file_purchases
        WHERE payment_id=$1
        ORDER BY created_at DESC
        LIMIT 1
        """,
        payment_id,
    )


# ============================================================
# GET LATEST PURCHASE
# ============================================================

async def get_latest_purchase(
    user_id: int,
    file_code: str,
):
    """
    Ambil transaksi terakhir user untuk file tertentu.
    """

    return await fetchrow(
        """
        SELECT
            id,
            user_id,
            file_code,
            created_at,
            owner_id,
            paid_price,
            payment_id,
            status,
            qr_message_id,
            qr_chat_id,
            paid_at,
            qr_string,
            qr_image,
            payment_url,
            expires_at,
            code
        FROM file_purchases
        WHERE user_id=$1
          AND file_code=$2
        ORDER BY created_at DESC, id DESC
        LIMIT 1
        """,
        user_id,
        file_code,
    )


# ============================================================
# GET FILE
# ============================================================

async def get_file_by_code(
    code: str,
):
    """
    Ambil file berdasarkan code.
    """

    code = safe_str(code)

    if not code:
        return None

    return await fetchrow(
        """
        SELECT *
        FROM files
        WHERE code=$1
        LIMIT 1
        """,
        code,
    )


# ============================================================
# OWNERSHIP CHECK
# ============================================================

def purchase_belongs_to_user(
    purchase,
    user_id: int,
) -> bool:
    """
    Pastikan transaksi benar-benar milik user
    yang menekan tombol.
    """

    if not purchase:
        return False

    try:
        purchase_user_id = purchase.get(
            "user_id"
        )

        if purchase_user_id is None:
            return False

        return int(
            purchase_user_id
        ) == int(user_id)

    except Exception:

        logger.exception(
            "DOMPETX OWNERSHIP CHECK ERROR"
        )

        return False


# ============================================================
# DATABASE CANCEL
# ============================================================

async def cancel_dompetx_database(
    payment_id: str,
) -> bool:
    """
    Ubah transaksi pending menjadi cancel.
    """

    payment_id = safe_str(payment_id)

    if not payment_id:
        return False

    try:

        result = await execute(
            """
            UPDATE file_purchases
            SET
                status='cancel'
            WHERE payment_id=$1
              AND status='pending'
            """,
            payment_id,
        )

        logger.info(
            "DOMPETX DATABASE CANCEL | payment_id=%s | result=%s",
            payment_id,
            result,
        )

        return True

    except Exception:

        logger.exception(
            "DOMPETX DATABASE CANCEL ERROR | payment_id=%s",
            payment_id,
        )

        return False


# ============================================================
# PROVIDER CANCEL
# ============================================================

async def cancel_dompetx_provider(
    payment_id: str,
) -> bool:
    """
    Cancel transaksi pada provider DompetX.
    """

    payment_id = safe_str(payment_id)

    if not payment_id:
        return False

    try:

        result = await DompetX.cancel_payment(
            payment_id
        )

        logger.info(
            "DOMPETX PROVIDER CANCEL | "
            "payment_id=%s | result=%s",
            payment_id,
            result,
        )

        return True

    except Exception:

        logger.exception(
            "DOMPETX PROVIDER CANCEL ERROR | "
            "payment_id=%s",
            payment_id,
        )

        return False


# ============================================================
# DELETE QR MESSAGE
# ============================================================

async def delete_qr_message(
    bot,
    purchase,
):
    """
    Hapus pesan QR dari Telegram jika ID tersedia.
    """

    if not purchase:
        return

    try:

        qr_chat_id = purchase.get(
            "qr_chat_id"
        )

        qr_message_id = purchase.get(
            "qr_message_id"
        )

        if not qr_chat_id:
            return

        if not qr_message_id:
            return

        await bot.delete_message(
            chat_id=int(qr_chat_id),
            message_id=int(qr_message_id),
        )

        logger.info(
            "DOMPETX QR MESSAGE DELETED | "
            "chat=%s | message=%s",
            qr_chat_id,
            qr_message_id,
        )

    except Exception:

        logger.warning(
            "DOMPETX DELETE QR MESSAGE FAILED",
            exc_info=True,
        )


# ============================================================
# AMOUNT VALIDATION
# ============================================================

def validate_payment_amount(
    provider_result,
    purchase,
) -> bool:
    """
    Validasi nominal pembayaran.

    Jika provider mengembalikan amount, nominal WAJIB sama.
    Jika provider tidak mengembalikan amount, kita tidak
    menggagalkan transaksi hanya karena field tersebut tidak ada.
    """

    provider_amount = safe_int(
        provider_result.get("amount")
        if provider_result
        else None
    )

    purchase_amount = safe_int(
        purchase.get("paid_price")
        if purchase
        else None
    )

    if purchase_amount <= 0:
        logger.error(
            "DOMPETX INVALID PURCHASE AMOUNT | "
            "payment=%s | db=%s",
            purchase.get("payment_id")
            if purchase
            else None,
            purchase_amount,
        )

        return False

    # Provider tidak mengirim amount.
    # Jangan gagal hanya karena field tidak tersedia.
    if provider_amount <= 0:
        logger.warning(
            "DOMPETX PROVIDER AMOUNT NOT AVAILABLE | "
            "payment=%s | db_amount=%s",
            purchase.get("payment_id")
            if purchase
            else None,
            purchase_amount,
        )

        return True

    if provider_amount != purchase_amount:

        logger.error(
            "DOMPETX AMOUNT MISMATCH | "
            "payment=%s | provider=%s | db=%s",
            purchase.get("payment_id")
            if purchase
            else None,
            provider_amount,
            purchase_amount,
        )

        return False

    return True


# ============================================================
# FORMAT EXPIRED
# ============================================================

def format_expires_at(
    expires_at: Any,
) -> Optional[str]:
    """
    Format expires_at tanpa error jika timezone/format berbeda.
    """

    if not expires_at:
        return None

    try:

        return expires_at.strftime(
            "%d-%m-%Y %H:%M:%S %z"
        )

    except Exception:

        try:
            return str(
                expires_at
            )

        except Exception:
            return None


# ============================================================
# BUILD PAYMENT CAPTION
# ============================================================

def build_payment_caption(
    file_title: str,
    payment_id: str,
    price: int,
    expires_at: Any = None,
) -> str:

    caption = (
        "💳 <b>PEMBAYARAN FILE</b>\n\n"
        f"📄 File:\n"
        f"<b>{file_title}</b>\n\n"
        f"🧾 Invoice:\n"
        f"<code>{payment_id}</code>\n\n"
        f"💰 Total:\n"
        f"<b>{format_rupiah(price)}</b>\n\n"
        "📷 Silakan scan QRIS di atas.\n\n"
        "Setelah pembayaran berhasil, "
        "tekan <b>🔄 Cek Pembayaran</b>.\n\n"
        "❌ Jika ingin membatalkan, "
        "tekan <b>Batalkan Pembayaran</b>."
    )

    formatted_expired = format_expires_at(
        expires_at
    )

    if formatted_expired:

        caption += (
            "\n\n⏰ Expired:\n"
            f"<code>{formatted_expired}</code>"
        )

    return caption


# ============================================================
# SEND QR
# ============================================================

async def send_dompetx_qr(
    bot,
    chat_id: int,
    qr_string: str,
    caption: str,
    payment_id: str,
):
    """
    Generate dan kirim QR DompetX.
    """

    qr_data = generate_qr(
        qr_string
    )

    message = await bot.send_photo(
        chat_id=chat_id,
        photo=BufferedInputFile(
            qr_data,
            filename="dompetx_qris.png",
        ),
        caption=caption,
        parse_mode="HTML",
        reply_markup=dompetx_keyboard(
            payment_id
        ),
    )

    return message


# ============================================================
# CREATE DOMPETX PAYMENT
# ============================================================

@router.callback_query(
    F.data.startswith("dompetx:")
)
async def create_dompetx(
    call: CallbackQuery,
):

    # ========================================================
    # CALLBACK DATA
    # ========================================================

    code = safe_str(
        call.data.split(
            ":",
            1,
        )[1]
    )

    user_id = call.from_user.id

    if not code:

        return await call.answer(
            "❌ Kode file tidak valid.",
            show_alert=True,
        )

    # ========================================================
    # FILE
    # ========================================================

    try:

        file = await get_file_by_code(
            code
        )

    except Exception:

        logger.exception(
            "DOMPETX FILE QUERY ERROR | code=%s",
            code,
        )

        return await call.answer(
            "❌ Gagal mengambil data file.",
            show_alert=True,
        )

    if not file:

        return await call.answer(
            "❌ File tidak ditemukan.",
            show_alert=True,
        )

    # ========================================================
    # PRICE
    # ========================================================

    price = safe_int(
        file.get("price")
    )

    if price <= 0:

        logger.error(
            "DOMPETX INVALID FILE PRICE | "
            "code=%s | price=%s",
            code,
            file.get("price"),
        )

        return await call.answer(
            "❌ Harga file tidak valid.",
            show_alert=True,
        )

    # ========================================================
    # OWNER
    # ========================================================

    owner_id = file.get(
        "owner_id"
    )

    if owner_id is None:

        logger.error(
            "DOMPETX OWNER ID KOSONG | code=%s",
            code,
        )

        return await call.answer(
            "❌ Pemilik file tidak ditemukan.",
            show_alert=True,
        )

    owner_id = safe_int(
        owner_id
    )

    if owner_id <= 0:

        return await call.answer(
            "❌ Pemilik file tidak valid.",
            show_alert=True,
        )

    # ========================================================
    # CHECK LAST PURCHASE
    # ========================================================

    try:

        existing = await get_latest_purchase(
            user_id,
            code,
        )

    except Exception:

        logger.exception(
            "DOMPETX PURCHASE QUERY ERROR | "
            "user=%s | code=%s",
            user_id,
            code,
        )

        return await call.answer(
            "❌ Gagal mengecek transaksi.",
            show_alert=True,
        )

    # ========================================================
    # ALREADY PAID
    # ========================================================

    if existing:

        existing_status = normalize_status(
            existing.get("status")
        )

        if existing_status == PURCHASE_PAID:

            return await call.answer(
                "✅ File ini sudah kamu beli.",
                show_alert=True,
            )

    # ========================================================
    # EXISTING PENDING PAYMENT
    # ========================================================

    if existing:

        existing_status = normalize_status(
            existing.get("status")
        )

        if existing_status == PURCHASE_PENDING:

            old_payment_id = safe_str(
                existing.get("payment_id")
            )

            if old_payment_id:

                await call.answer(
                    "🔄 Mengecek pembayaran sebelumnya..."
                )

                old_result = None

                try:

                    old_result = (
                        await DompetX.check_payment(
                            old_payment_id
                        )
                    )

                except Exception:

                    logger.exception(
                        "DOMPETX CHECK OLD PAYMENT ERROR | "
                        "payment_id=%s",
                        old_payment_id,
                    )

                # ====================================================
                # PROVIDER RESPONSE EXISTS
                # ====================================================

                if old_result:

                    old_status = normalize_status(
                        old_result.get("status")
                    )

                    logger.info(
                        "DOMPETX OLD PAYMENT | "
                        "payment_id=%s | status=%s",
                        old_payment_id,
                        old_status,
                    )

                    # ==================================================
                    # OLD PAYMENT SUCCESS
                    # ==================================================

                    if old_status in SUCCESS_STATUSES:

                        purchase = await get_dompetx_purchase(
                            old_payment_id
                        )

                        if not purchase:

                            return await call.answer(
                                "❌ Data transaksi tidak ditemukan.",
                                show_alert=True,
                            )

                        old_file = await get_file_by_code(
                            safe_str(
                                purchase.get(
                                    "file_code"
                                )
                            )
                        )

                        if not old_file:

                            return await call.answer(
                                "❌ File tidak ditemukan.",
                                show_alert=True,
                            )

                        if not validate_payment_amount(
                            old_result,
                            purchase,
                        ):

                            return await call.answer(
                                "❌ Nominal pembayaran tidak sesuai.",
                                show_alert=True,
                            )

                        success = await finish_payment(
                            call.bot,
                            purchase,
                            old_file,
                            old_payment_id,
                            call.message,
                        )

                        if success:
                            return

                        return await call.answer(
                            "⚠️ Pembayaran sudah diproses atau gagal diproses.",
                            show_alert=True,
                        )

                    # ==================================================
                    # OLD PAYMENT STILL ACTIVE
                    # ==================================================

                    if old_status in ACTIVE_STATUSES:

                        old_qr_string = safe_str(
                            existing.get(
                                "qr_string"
                            )
                        )

                        if old_qr_string:

                            try:

                                old_title = get_file_title(
                                    file
                                )

                                old_caption = build_payment_caption(
                                    old_title,
                                    old_payment_id,
                                    price,
                                    existing.get(
                                        "expires_at"
                                    ),
                                )

                                await send_dompetx_qr(
                                    call.bot,
                                    call.message.chat.id,
                                    old_qr_string,
                                    (
                                        "💳 <b>PEMBAYARAN MASIH BERJALAN</b>\n\n"
                                        + old_caption.replace(
                                            "💳 <b>PEMBAYARAN FILE</b>\n\n",
                                            "",
                                            1,
                                        )
                                    ),
                                    old_payment_id,
                                )

                                return

                            except Exception:

                                logger.exception(
                                    "DOMPETX RESEND OLD QR ERROR | "
                                    "payment_id=%s",
                                    old_payment_id,
                                )

                        return await call.answer(
                            "⏳ Pembayaran sebelumnya masih aktif.",
                            show_alert=True,
                        )

                    # ==================================================
                    # OLD PAYMENT FAILED
                    # ==================================================

                    if old_status in FAILED_STATUSES:

                        logger.info(
                            "DOMPETX OLD PAYMENT FAILED | "
                            "payment_id=%s | status=%s",
                            old_payment_id,
                            old_status,
                        )

                        await cancel_dompetx_database(
                            old_payment_id
                        )

                    # ==================================================
                    # UNKNOWN STATUS
                    # ==================================================

                    else:

                        if old_status not in FAILED_STATUSES:

                            logger.warning(
                                "DOMPETX UNKNOWN STATUS | "
                                "payment_id=%s | status=%s",
                                old_payment_id,
                                old_status,
                            )

                            return await call.answer(
                                f"⏳ Status pembayaran: {old_status}",
                                show_alert=True,
                            )

    # ========================================================
    # CREATE NEW PAYMENT
    # ========================================================

    await call.answer(
        "⏳ Membuat QRIS DompetX..."
    )

    try:

        payment = await DompetX.create_payment(
            amount=price,
            description=f"File {code}",
            customer_name=safe_str(
                call.from_user.full_name,
                "Customer",
            ),
        )

    except Exception:

        logger.exception(
            "DOMPETX CREATE PAYMENT ERROR | "
            "user=%s | code=%s | amount=%s",
            user_id,
            code,
            price,
        )

        return await call.message.answer(
            "❌ DompetX sedang mengalami gangguan."
        )

    # ========================================================
    # PAYMENT RESPONSE
    # ========================================================

    if not payment:

        logger.error(
            "DOMPETX EMPTY PAYMENT RESPONSE | "
            "user=%s | code=%s",
            user_id,
            code,
        )

        return await call.message.answer(
            "❌ Gagal membuat pembayaran DompetX."
        )

    # ========================================================
    # PAYMENT ID
    # ========================================================

    payment_id = safe_str(
        payment.get("payment_id")
    )

    if not payment_id:

        logger.error(
            "DOMPETX PAYMENT ID KOSONG | response=%s",
            payment,
        )

        return await call.message.answer(
            "❌ Payment ID tidak ditemukan."
        )

    # ========================================================
    # QR STRING
    # ========================================================

    qr_string = safe_str(
        payment.get("qr_string")
    )

    if not qr_string:

        logger.error(
            "DOMPETX QR STRING KOSONG | "
            "payment_id=%s | response=%s",
            payment_id,
            payment,
        )

        await cancel_dompetx_provider(
            payment_id
        )

        return await call.message.answer(
            "❌ QRIS DompetX tidak tersedia."
        )

    # ========================================================
    # OPTIONAL PAYMENT DATA
    # ========================================================

    expires_at = payment.get(
        "expires_at"
    )

    qr_image = safe_str(
        payment.get("qr_image")
    ) or None

    payment_url = safe_str(
        payment.get("payment_url")
    ) or None

    # ========================================================
    # SAVE PURCHASE
    # ========================================================

    try:

        if existing:

            # ------------------------------------------------
            # REUSE OLD ROW
            # ------------------------------------------------

            saved_purchase = await fetchrow(
                """
                UPDATE file_purchases
                SET
                    user_id=$1,
                    file_code=$2,
                    code=$2,
                    owner_id=$3,
                    paid_price=$4,
                    payment_id=$5,
                    status='pending',
                    qr_string=$6,
                    qr_image=$7,
                    payment_url=$8,
                    expires_at=$9,
                    qr_message_id=NULL,
                    qr_chat_id=NULL,
                    paid_at=NULL,
                    created_at=NOW()
                WHERE id=$10
                RETURNING *
                """,
                user_id,
                code,
                owner_id,
                price,
                payment_id,
                qr_string,
                qr_image,
                payment_url,
                expires_at,
                existing["id"],
            )

        else:

            # ------------------------------------------------
            # CREATE NEW ROW
            # ------------------------------------------------

            saved_purchase = await fetchrow(
                """
                INSERT INTO file_purchases
                (
                    user_id,
                    file_code,
                    code,
                    owner_id,
                    paid_price,
                    payment_id,
                    status,
                    qr_string,
                    qr_image,
                    payment_url,
                    expires_at,
                    qr_message_id,
                    qr_chat_id,
                    paid_at,
                    created_at
                )
                VALUES
                (
                    $1,
                    $2,
                    $2,
                    $3,
                    $4,
                    $5,
                    'pending',
                    $6,
                    $7,
                    $8,
                    $9,
                    NULL,
                    NULL,
                    NULL,
                    NOW()
                )
                RETURNING *
                """,
                user_id,
                code,
                owner_id,
                price,
                payment_id,
                qr_string,
                qr_image,
                payment_url,
                expires_at,
            )

    except Exception:

        logger.exception(
            "DOMPETX SAVE PURCHASE ERROR | "
            "payment_id=%s | user=%s | code=%s",
            payment_id,
            user_id,
            code,
        )

        await cancel_dompetx_provider(
            payment_id
        )

        return await call.message.answer(
            "❌ Gagal menyimpan transaksi."
        )

    if not saved_purchase:

        logger.error(
            "DOMPETX PURCHASE NOT SAVED | "
            "payment_id=%s",
            payment_id,
        )

        await cancel_dompetx_provider(
            payment_id
        )

        return await call.message.answer(
            "❌ Transaksi gagal dibuat."
        )

    # ========================================================
    # GENERATE QR
    # ========================================================

    try:

        qr_data = generate_qr(
            qr_string
        )

    except Exception:

        logger.exception(
            "DOMPETX QR GENERATE ERROR | "
            "payment_id=%s",
            payment_id,
        )

        await cancel_dompetx_database(
            payment_id
        )

        await cancel_dompetx_provider(
            payment_id
        )

        return await call.message.answer(
            "❌ Gagal membuat QRIS."
        )

    # ========================================================
    # CAPTION
    # ========================================================

    caption = build_payment_caption(
        get_file_title(file),
        payment_id,
        price,
        expires_at,
    )

    # ========================================================
    # SEND QR
    # ========================================================

    try:

        msg = await call.message.answer_photo(
            BufferedInputFile(
                qr_data,
                filename="dompetx_qris.png",
            ),
            caption=caption,
            parse_mode="HTML",
            reply_markup=dompetx_keyboard(
                payment_id
            ),
        )

    except Exception:

        logger.exception(
            "DOMPETX SEND QR ERROR | "
            "payment_id=%s",
            payment_id,
        )

        await cancel_dompetx_database(
            payment_id
        )

        await cancel_dompetx_provider(
            payment_id
        )

        return await call.message.answer(
            "❌ Gagal mengirim QRIS."
        )

    # ========================================================
    # SAVE TELEGRAM QR MESSAGE
    # ========================================================

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
            payment_id,
        )

    except Exception:

        logger.exception(
            "DOMPETX SAVE QR MESSAGE ERROR | "
            "payment_id=%s",
            payment_id,
        )

    # ========================================================
    # LOG
    # ========================================================

    logger.info(
        "DOMPETX PAYMENT CREATED | "
        "payment_id=%s | user=%s | code=%s | "
        "amount=%s | expires=%s",
        payment_id,
        user_id,
        code,
        price,
        expires_at,
    )


# ============================================================
# CHECK DOMPETX PAYMENT
# ============================================================

@router.callback_query(
    F.data.startswith("dompetxcheck:")
)
async def check_dompetx(
    call: CallbackQuery,
):

    payment_id = safe_str(
        call.data.split(
            ":",
            1,
        )[1]
    )

    if not payment_id:

        return await call.answer(
            "❌ Payment ID tidak valid.",
            show_alert=True,
        )

    # ========================================================
    # LOCK
    # ========================================================

    if payment_id in CHECK_LOCK:

        return await call.answer(
            "⏳ Sedang diproses...",
            show_alert=True,
        )

    CHECK_LOCK.add(
        payment_id
    )

    try:

        await call.answer(
            "🔄 Mengecek pembayaran..."
        )

        # ====================================================
        # PURCHASE
        # ====================================================

        purchase = await get_dompetx_purchase(
            payment_id
        )

        if not purchase:

            return await call.message.answer(
                "❌ Data pembayaran tidak ditemukan."
            )

        # ====================================================
        # SECURITY
        # ====================================================

        if not purchase_belongs_to_user(
            purchase,
            call.from_user.id,
        ):

            logger.warning(
                "UNAUTHORIZED DOMPETX CHECK | "
                "payment_id=%s | owner=%s | caller=%s",
                payment_id,
                purchase.get("user_id"),
                call.from_user.id,
            )

            return await call.answer(
                "❌ Pembayaran ini bukan milik kamu.",
                show_alert=True,
            )

        # ====================================================
        # ALREADY PAID
        # ====================================================

        purchase_status = normalize_status(
            purchase.get("status")
        )

        if purchase_status == PURCHASE_PAID:

            return await call.answer(
                "✅ Pembayaran sudah diproses.",
                show_alert=True,
            )

        # ====================================================
        # PROVIDER CHECK
        # ====================================================

        try:

            result = await DompetX.check_payment(
                payment_id
            )

        except Exception:

            logger.exception(
                "DOMPETX CHECK PROVIDER ERROR | "
                "payment_id=%s",
                payment_id,
            )

            return await call.answer(
                "❌ Gagal terhubung ke DompetX.",
                show_alert=True,
            )

        if not result:

            return await call.answer(
                "❌ Gagal mengecek pembayaran.",
                show_alert=True,
            )

        # ====================================================
        # STATUS
        # ====================================================

        status = normalize_status(
            result.get("status")
        )

        logger.info(
            "DOMPETX CHECK | "
            "payment_id=%s | status=%s | result=%s",
            payment_id,
            status,
            result,
        )

        # ====================================================
        # FAILED
        # ====================================================

        if status in FAILED_STATUSES:

            await cancel_dompetx_database(
                payment_id
            )

            await delete_qr_message(
                call.bot,
                purchase,
            )

            return await call.answer(
                f"❌ Pembayaran {status}.",
                show_alert=True,
            )

        # ====================================================
        # NOT PAID
        # ====================================================

        if status not in SUCCESS_STATUSES:

            return await call.answer(
                "⏳ Pembayaran belum diterima.",
                show_alert=True,
            )

        # ====================================================
        # AMOUNT VALIDATION
        # ====================================================

        if not validate_payment_amount(
            result,
            purchase,
        ):

            logger.error(
                "DOMPETX PAYMENT REJECTED "
                "BECAUSE OF AMOUNT MISMATCH | "
                "payment_id=%s",
                payment_id,
            )

            return await call.answer(
                "❌ Nominal pembayaran tidak sesuai.",
                show_alert=True,
            )

        # ====================================================
        # FILE
        # ====================================================

        file_code = safe_str(
            purchase.get(
                "file_code"
            )
        )

        if not file_code:

            logger.error(
                "DOMPETX FILE CODE EMPTY | "
                "payment_id=%s",
                payment_id,
            )

            return await call.answer(
                "❌ Kode file transaksi tidak ditemukan.",
                show_alert=True,
            )

        file = await get_file_by_code(
            file_code
        )

        if not file:

            logger.error(
                "DOMPETX FILE NOT FOUND | "
                "payment_id=%s | code=%s",
                payment_id,
                file_code,
            )

            return await call.answer(
                "❌ File tidak ditemukan.",
                show_alert=True,
            )

        # ====================================================
        # FINISH PAYMENT
        # ====================================================

        success = await finish_payment(
            call.bot,
            purchase,
            file,
            payment_id,
            call.message,
        )

        if success:

            logger.info(
                "DOMPETX PAYMENT FINISHED | "
                "payment_id=%s | user=%s | file=%s",
                payment_id,
                call.from_user.id,
                file_code,
            )

            return

        return await call.answer(
            "⚠️ Pembayaran sudah diproses atau gagal diproses.",
            show_alert=True,
        )

    except Exception:

        logger.exception(
            "DOMPETX CHECK ERROR | payment_id=%s",
            payment_id,
        )

        try:

            await call.answer(
                "❌ Terjadi kesalahan saat memproses pembayaran.",
                show_alert=True,
            )

        except Exception:
            pass

    finally:

        CHECK_LOCK.discard(
            payment_id
        )


# ============================================================
# CANCEL DOMPETX PAYMENT
# ============================================================

@router.callback_query(
    F.data.startswith("dompetxcancel:")
)
async def cancel_dompetx(
    call: CallbackQuery,
):

    payment_id = safe_str(
        call.data.split(
            ":",
            1,
        )[1]
    )

    if not payment_id:

        return await call.answer(
            "❌ Payment ID tidak valid.",
            show_alert=True,
        )

    # ========================================================
    # PURCHASE
    # ========================================================

    payment = await get_dompetx_purchase(
        payment_id
    )

    if not payment:

        return await call.answer(
            "❌ Data pembayaran tidak ditemukan.",
            show_alert=True,
        )

    # ========================================================
    # SECURITY
    # ========================================================

    if not purchase_belongs_to_user(
        payment,
        call.from_user.id,
    ):

        logger.warning(
            "UNAUTHORIZED DOMPETX CANCEL | "
            "payment_id=%s | owner=%s | caller=%s",
            payment_id,
            payment.get("user_id"),
            call.from_user.id,
        )

        return await call.answer(
            "❌ Pembayaran ini bukan milik kamu.",
            show_alert=True,
        )

    # ========================================================
    # STATUS
    # ========================================================

    status = normalize_status(
        payment.get("status")
    )

    if status == PURCHASE_PAID:

        return await call.answer(
            "❌ Pembayaran sudah dibayar.",
            show_alert=True,
        )

    if status != PURCHASE_PENDING:

        return await call.answer(
            f"⚠️ Pembayaran sudah berstatus {status}.",
            show_alert=True,
        )

    # ========================================================
    # LOCK CHECK
    # ========================================================

    if payment_id in CHECK_LOCK:

        return await call.answer(
            "⏳ Pembayaran sedang diproses. Coba lagi.",
            show_alert=True,
        )

    # ========================================================
    # CANCEL PROVIDER
    # ========================================================

    provider_cancelled = (
        await cancel_dompetx_provider(
            payment_id
        )
    )

    if not provider_cancelled:

        logger.warning(
            "DOMPETX PROVIDER CANCEL FAILED | "
            "payment_id=%s",
            payment_id,
        )

    # ========================================================
    # CANCEL DATABASE
    # ========================================================

    database_cancelled = (
        await cancel_dompetx_database(
            payment_id
        )
    )

    if not database_cancelled:

        return await call.answer(
            "❌ Gagal membatalkan transaksi.",
            show_alert=True,
        )

    # ========================================================
    # DELETE QR
    # ========================================================

    await delete_qr_message(
        call.bot,
        payment,
    )

    # ========================================================
    # REMOVE BUTTON
    # ========================================================

    try:

        await call.message.edit_reply_markup(
            reply_markup=None
        )

    except Exception:

        pass

    # ========================================================
    # FEEDBACK
    # ========================================================

    await call.answer(
        "✅ Pembayaran dibatalkan.",
        show_alert=True,
    )

    logger.info(
        "DOMPETX PAYMENT CANCELLED | "
        "payment_id=%s | user=%s | "
        "provider_cancelled=%s | database_cancelled=%s",
        payment_id,
        call.from_user.id,
        provider_cancelled,
        database_cancelled,
    )


# ============================================================
# END OF FILE
# ============================================================
