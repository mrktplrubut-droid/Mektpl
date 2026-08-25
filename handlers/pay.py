import json
import logging
import qrcode
import secrets

from io import BytesIO

from aiogram import Router, F
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    BufferedInputFile,
)

from database import fetchrow, execute

from utils.redis_client import (
    safe_set,
    safe_get,
    safe_delete,
)

from utils.bayargg import BayarGG

from config import (
    STORAGE_CHANNEL_ID,
    NOTIF_CHANNEL_ID,
    ADMIN_IDS,
    MANUAL_QR_FILE_ID,
)


logger = logging.getLogger(__name__)

router = Router()


# ============================================================
# CONFIG
# ============================================================

PAY_LOCK_TTL = 30
MEDIA_TTL = 3600
PER_PAGE = 10

# Dipakai bersama dompetx.py
CHECK_LOCK = set()


# ============================================================
# PAYMENT STATUS
# ============================================================

SUCCESS_STATUSES = {
    "paid",
    "success",
    "settled",
    "completed",
}

FAILED_STATUSES = {
    "expired",
    "cancel",
    "cancelled",
    "canceled",
    "failed",
    "rejected",
}


# ============================================================
# HELPER
# ============================================================

def mask_user_id(user_id: int) -> str:

    uid = str(user_id)

    if len(uid) <= 4:
        return "****"

    return (
        uid[:2]
        + "****"
        + uid[-2:]
    )


def format_rupiah(amount) -> str:

    try:
        return f"Rp {int(amount):,}".replace(",", ".")

    except Exception:
        return f"Rp {amount}"


def normalize_status(value) -> str:

    return str(
        value or ""
    ).strip().lower()


def is_admin(user_id: int) -> bool:

    try:
        return int(user_id) in {
            int(x)
            for x in ADMIN_IDS
        }

    except Exception:
        return False


# ============================================================
# UPGRADE NOTIFICATION
# ============================================================

async def send_upgrade_notif(
    bot,
    user_id,
    tier,
):

    try:

        tier = str(
            tier or ""
        ).lower()

        masked = mask_user_id(
            user_id
        )

        if tier == "vip":

            text = (
                "🌟 <b>VIP UPGRADE</b>\n\n"
                f"👤 User: <code>{masked}</code>\n"
                "📦 Paket: VIP"
            )

        elif tier == "vvip":

            text = (
                "👑 <b>VVIP UPGRADE</b>\n\n"
                f"👤 User: <code>{masked}</code>\n"
                "📦 Paket: VVIP"
            )

        else:
            return

        await bot.send_message(
            NOTIF_CHANNEL_ID,
            text,
            parse_mode="HTML",
        )

    except Exception:

        logger.exception(
            "UPGRADE NOTIF ERROR"
        )


# ============================================================
# PAYMENT METHOD KEYBOARD
# ============================================================

def payment_method_keyboard(code):

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="⚡ QR Otomatis 1",
                    callback_data=f"auto:{code}",
                )
            ],
            [
                InlineKeyboardButton(
                    text="💳 QR Otomatis 2",
                    callback_data=f"dompetx:{code}",
                )
            ],
            [
                InlineKeyboardButton(
                    text="📷 QR Manual",
                    callback_data=f"manual:{code}",
                )
            ],
        ]
    )


def fallback_auto1_keyboard(code):

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="💳 QR Otomatis 2",
                    callback_data=f"dompetx:{code}",
                )
            ],
            [
                InlineKeyboardButton(
                    text="📷 QR Manual",
                    callback_data=f"manual:{code}",
                )
            ],
        ]
    )


def fallback_auto2_keyboard(code):

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📷 QR Manual",
                    callback_data=f"manual:{code}",
                )
            ]
        ]
    )


def manual_payment_keyboard(code):

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Saya Sudah Bayar",
                    callback_data=f"manualcheck:{code}",
                )
            ],
            [
                InlineKeyboardButton(
                    text="❌ Batal",
                    callback_data="close",
                )
            ],
        ]
    )


def payment_check_keyboard(
    invoice,
    gateway="bayargg",
):

    if gateway == "dompetx":

        check_cb = f"dompetxcheck:{invoice}"
        cancel_cb = f"dompetxcancel:{invoice}"

    else:

        check_cb = f"check:{invoice}"
        cancel_cb = f"cancel:{invoice}"

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔄 Cek Pembayaran",
                    callback_data=check_cb,
                )
            ],
            [
                InlineKeyboardButton(
                    text="❌ Batalkan",
                    callback_data=cancel_cb,
                )
            ],
        ]
    )


# ============================================================
# MEDIA KEYBOARD
# ============================================================

def media_keyboard(
    media_id,
    page,
    total,
):

    max_page = (
        total + PER_PAGE - 1
    ) // PER_PAGE

    buttons = []

    nav = []

    if page > 1:

        nav.append(
            InlineKeyboardButton(
                text="⬅️",
                callback_data=(
                    f"mp:{media_id}:{page - 1}"
                ),
            )
        )

    nav.append(
        InlineKeyboardButton(
            text=f"{page}/{max_page}",
            callback_data="none",
        )
    )

    if page < max_page:

        nav.append(
            InlineKeyboardButton(
                text="➡️",
                callback_data=(
                    f"mp:{media_id}:{page + 1}"
                ),
            )
        )

    buttons.append(nav)

    buttons.append(
        [
            InlineKeyboardButton(
                text="📤 Kirim Halaman",
                callback_data=(
                    f"sp:{media_id}:{page}"
                ),
            )
        ]
    )

    buttons.append(
        [
            InlineKeyboardButton(
                text="📦 Kirim Semua",
                callback_data=(
                    f"sa:{media_id}"
                ),
            )
        ]
    )

    return InlineKeyboardMarkup(
        inline_keyboard=buttons
    )


# ============================================================
# FINISH PAYMENT
# ============================================================

async def finish_payment(
    bot,
    purchase,
    file,
    invoice,
    message,
):

    """
    CORE PAYMENT SUCCESS.

    Semua gateway wajib masuk ke sini:

    - BayarGG
    - DompetX
    - Manual Admin

    Fungsi ini bertanggung jawab untuk:

    1. Atomic update payment -> paid
    2. Membuat media session
    3. Menambah buy_count
    4. Membayar seller
    5. Membuat transaction
    6. Notification
    7. Hapus QR
    8. Kirim menu media

    Return:
        True  = sukses
        False = gagal / sudah diproses
    """

    try:

        purchase_id = purchase["id"]

        current_status = normalize_status(
            purchase["status"]
        )

        # ====================================================
        # SUDAH PAID
        # ====================================================

        if current_status == "paid":

            logger.info(
                "PAYMENT ALREADY PAID | "
                "purchase=%s | invoice=%s",
                purchase_id,
                invoice,
            )

            return False

        # ====================================================
        # PARSE MEDIA
        # ====================================================

        media_data = file["media"]

        if isinstance(
            media_data,
            str,
        ):

            try:

                media_list = json.loads(
                    media_data
                )

            except Exception:

                logger.exception(
                    "MEDIA JSON PARSE ERROR"
                )

                media_list = []

        else:

            media_list = (
                media_data or []
            )

        media_list = [
            item
            for item in media_list
            if isinstance(
                item,
                dict,
            )
            and item.get("message_id")
        ]

        if not media_list:

            await message.answer(
                "❌ Media file kosong."
            )

            return False

        # ====================================================
        # ATOMIC PAYMENT LOCK
        # ====================================================
        #
        # Ini bagian paling penting.
        #
        # Hanya transaksi dengan status pending
        # yang boleh berubah menjadi paid.
        #
        # Jika user menekan tombol berkali-kali,
        # hanya SATU proses yang mendapatkan row.
        #

        updated_purchase = await fetchrow(
            """
            UPDATE file_purchases
            SET
                status='paid',
                paid_at=COALESCE(paid_at, NOW())
            WHERE id=$1
              AND status='pending'
            RETURNING *
            """,
            purchase_id,
        )

        if not updated_purchase:

            logger.warning(
                "PAYMENT ALREADY PROCESSED | "
                "purchase=%s | invoice=%s",
                purchase_id,
                invoice,
            )

            return False

        purchase = updated_purchase

        # ====================================================
        # CREATE MEDIA SESSION
        # ====================================================

        media_id = secrets.token_hex(8)

        share_media = (
            file["share_media"]
            if "share_media" in file
            else False
        )

        await safe_set(
            f"paidmedia:{media_id}",
            {
                "media": media_list,
                "share_media": share_media,
                "invoice": invoice,
            },
            ex=MEDIA_TTL,
        )

        # ====================================================
        # BUY COUNT
        # ====================================================

        try:

            await execute(
                """
                UPDATE files
                SET buy_count = COALESCE(buy_count, 0) + 1,
                    sold = COALESCE(sold, 0) + 1
                WHERE code=$1
                """,
                file["code"],
            )

        except Exception:

            logger.exception(
                "BUY COUNT UPDATE ERROR"
            )

        # ====================================================
        # SELLER PROFIT
        # ====================================================

        try:

            price = int(
                file["price"] or 0
            )

            income = int(
                price * 0.5
            )

            owner_id = file["owner_id"]

            await execute(
                """
                UPDATE users
                SET
                    balance =
                        COALESCE(balance, 0) + $1,
                    total_earn =
                        COALESCE(total_earn, 0) + $1
                WHERE chat_id=$2
                """,
                income,
                owner_id,
            )

            await execute(
                """
                INSERT INTO transactions
                (
                    user_id,
                    type,
                    amount,
                    description
                )
                VALUES
                ($1, $2, $3, $4)
                """,
                owner_id,
                "file_sale",
                income,
                f"Pendapatan file {file['code']}",
            )

        except Exception:

            logger.exception(
                "SELLER PROFIT ERROR | "
                "purchase=%s",
                purchase_id,
            )

        # ====================================================
        # VIP / VVIP
        # ====================================================

        try:

            code_lower = str(
                file["code"]
            ).lower()

            if "vvip" in code_lower:

                await send_upgrade_notif(
                    bot,
                    purchase["user_id"],
                    "vvip",
                )

            elif "vip" in code_lower:

                await send_upgrade_notif(
                    bot,
                    purchase["user_id"],
                    "vip",
                )

        except Exception:

            logger.exception(
                "VIP NOTIFICATION ERROR"
            )

        # ====================================================
        # CHANNEL NOTIFICATION
        # ====================================================

        try:

            masked = mask_user_id(
                purchase["user_id"]
            )

            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="🛒 Buy Now",
                            url=(
                                "https://t.me/"
                                "mktplbot"
                                f"?start={file['code']}"
                            ),
                        )
                    ]
                ]
            )

            await bot.send_message(
                NOTIF_CHANNEL_ID,
                (
                    "💸 <b>FILE PAYMENT SUCCESS</b>\n\n"
                    f"📄 Judul: <b>{file['title']}</b>\n"
                    f"📁 Code: <code>{file['code']}</code>\n"
                    f"👤 User: <code>{masked}</code>"
                ),
                parse_mode="HTML",
                reply_markup=keyboard,
            )

        except Exception:

            logger.exception(
                "PAYMENT NOTIFICATION ERROR"
            )

        # ====================================================
        # DELETE QR MESSAGE
        # ====================================================

        try:

            qr_message_id = purchase.get(
                "qr_message_id"
            )

            qr_chat_id = purchase.get(
                "qr_chat_id"
            )

            if (
                qr_message_id
                and qr_chat_id
            ):

                await bot.delete_message(
                    chat_id=qr_chat_id,
                    message_id=qr_message_id,
                )

        except Exception:

            logger.warning(
                "DELETE PAYMENT QR FAILED",
                exc_info=True,
            )

        # ====================================================
        # SEND MEDIA MENU
        # ====================================================

        total = len(
            media_list
        )

        await message.answer(
            (
                "🎉 <b>Pembayaran berhasil!</b>\n\n"
                f"📦 Total File: <b>{total}</b>\n\n"
                "Silahkan pilih pengiriman:"
            ),
            parse_mode="HTML",
            reply_markup=media_keyboard(
                media_id,
                1,
                total,
            ),
        )

        logger.info(
            "PAYMENT FINISHED | "
            "purchase=%s | invoice=%s | "
            "user=%s | code=%s",
            purchase_id,
            invoice,
            purchase["user_id"],
            file["code"],
        )

        return True

    except Exception:

        logger.exception(
            "FINISH PAYMENT ERROR | "
            "purchase=%s | invoice=%s",
            purchase.get("id"),
            invoice,
        )

        return False


# ============================================================
# CHOOSE PAYMENT
# ============================================================

@router.callback_query(
    F.data.startswith("pay:")
)
async def choose_payment(
    call: CallbackQuery,
):

    code = call.data.split(
        ":",
        1,
    )[1]

    file = await fetchrow(
        """
        SELECT *
        FROM files
        WHERE code=$1
        """,
        code,
    )

    if not file:

        return await call.answer(
            "❌ File tidak ditemukan.",
            show_alert=True,
        )

    price = int(
        file["price"] or 0
    )

    await call.message.edit_text(
        (
            "💳 <b>PILIH PEMBAYARAN</b>\n\n"
            f"📦 File: <b>{file['title']}</b>\n"
            f"💰 Harga: <b>{format_rupiah(price)}</b>\n\n"
            "Silahkan pilih metode pembayaran."
        ),
        parse_mode="HTML",
        reply_markup=payment_method_keyboard(
            code
        ),
    )

    await call.answer()


# ============================================================
# BAYARGG CREATE
# ============================================================

@router.callback_query(
    F.data.startswith("auto:")
)
async def pay_file(
    call: CallbackQuery,
):

    user_id = call.from_user.id

    code = call.data.split(
        ":",
        1,
    )[1]

    await call.answer(
        "⏳ Membuat pembayaran..."
    )

    # ========================================================
    # FILE
    # ========================================================

    file = await fetchrow(
        """
        SELECT *
        FROM files
        WHERE code=$1
        """,
        code,
    )

    if not file:

        return await call.answer(
            "❌ File tidak ditemukan.",
            show_alert=True,
        )

    price = int(
        file["price"] or 0
    )

    if price <= 0:

        return await call.answer(
            "❌ Harga file tidak valid.",
            show_alert=True,
        )

    # ========================================================
    # CEK PURCHASE PENDING
    # ========================================================

    existing = await fetchrow(
        """
        SELECT *
        FROM file_purchases
        WHERE user_id=$1
          AND file_code=$2
          AND status='pending'
        ORDER BY id DESC
        LIMIT 1
        """,
        user_id,
        code,
    )

    if existing:

        return await call.answer(
            "⏳ Kamu masih memiliki pembayaran yang belum selesai.",
            show_alert=True,
        )

    # ========================================================
    # CREATE BAYARGG
    # ========================================================

    try:

        data = await BayarGG.create_payment(
            amount=price,
            description=f"File {code}",
            customer_name=call.from_user.full_name,
        )

    except Exception:

        logger.exception(
            "BAYARGG CREATE ERROR"
        )

        data = None

    if not data:

        await call.message.answer(
            (
                "⚠️ <b>QR OTOMATIS 1 TIDAK TERSEDIA</b>\n\n"
                "Sistem QR Otomatis 1 sedang mengalami gangguan.\n\n"
                "Silahkan gunakan metode pembayaran lain."
            ),
            parse_mode="HTML",
            reply_markup=fallback_auto1_keyboard(
                code
            ),
        )

        return

    invoice = data.get(
        "invoice_id"
    )

    qr_string = data.get(
        "qris_string"
    )

    if not invoice or not qr_string:

        logger.error(
            "BAYARGG INVALID RESPONSE: %s",
            data,
        )

        await call.message.answer(
            "❌ Data pembayaran dari gateway tidak lengkap.",
            reply_markup=fallback_auto1_keyboard(
                code
            ),
        )

        return

    # ========================================================
    # SAVE PURCHASE
    # ========================================================

    try:

        purchase = await fetchrow(
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
                NOW()
            )
            RETURNING *
            """,
            user_id,
            code,
            file["owner_id"],
            price,
            invoice,
            qr_string,
        )

    except Exception:

        logger.exception(
            "BAYARGG SAVE PURCHASE ERROR"
        )

        try:
            await BayarGG.cancel_payment(
                invoice
            )
        except Exception:
            pass

        return await call.message.answer(
            "❌ Gagal menyimpan transaksi."
        )

    # ========================================================
    # GENERATE QR
    # ========================================================

    try:

        qr = qrcode.make(
            qr_string
        )

        buffer = BytesIO()

        qr.save(
            buffer,
            format="PNG",
        )

        buffer.seek(0)

        qr_data = buffer.getvalue()

    except Exception:

        logger.exception(
            "BAYARGG QR GENERATE ERROR"
        )

        try:
            await BayarGG.cancel_payment(
                invoice
            )
        except Exception:
            pass

        await execute(
            """
            UPDATE file_purchases
            SET status='cancel'
            WHERE id=$1
              AND status='pending'
            """,
            purchase["id"],
        )

        return await call.message.answer(
            "❌ Gagal membuat QRIS."
        )

    # ========================================================
    # SEND QR
    # ========================================================

    try:

        msg = await call.message.answer_photo(
            BufferedInputFile(
                qr_data,
                filename="bayargg_qris.png",
            ),
            caption=(
                "💳 <b>PAYMENT QRIS</b>\n\n"
                f"🧾 Invoice:\n"
                f"<code>{invoice}</code>\n\n"
                f"💰 Total:\n"
                f"<b>{format_rupiah(price)}</b>\n\n"
                "📷 Scan QR untuk melakukan pembayaran.\n\n"
                "Setelah membayar, tekan "
                "<b>🔄 Cek Pembayaran</b>."
            ),
            parse_mode="HTML",
            reply_markup=payment_check_keyboard(
                invoice,
                "bayargg",
            ),
        )

    except Exception:

        logger.exception(
            "BAYARGG SEND QR ERROR"
        )

        try:
            await BayarGG.cancel_payment(
                invoice
            )
        except Exception:
            pass

        await execute(
            """
            UPDATE file_purchases
            SET status='cancel'
            WHERE id=$1
              AND status='pending'
            """,
            purchase["id"],
        )

        return

    # ========================================================
    # SAVE QR MESSAGE
    # ========================================================

    await execute(
        """
        UPDATE file_purchases
        SET
            qr_message_id=$1,
            qr_chat_id=$2
        WHERE id=$3
        """,
        msg.message_id,
        msg.chat.id,
        purchase["id"],
    )

    logger.info(
        "BAYARGG PAYMENT CREATED | "
        "purchase=%s | invoice=%s | "
        "user=%s | code=%s | amount=%s",
        purchase["id"],
        invoice,
        user_id,
        code,
        price,
    )


# ============================================================
# BAYARGG CHECK
# ============================================================

@router.callback_query(
    F.data.startswith("check:")
)
async def check_payment(
    call: CallbackQuery,
):

    invoice = call.data.split(
        ":",
        1,
    )[1]

    if invoice in CHECK_LOCK:

        return await call.answer(
            "⏳ Sedang diproses...",
            show_alert=True,
        )

    CHECK_LOCK.add(
        invoice
    )

    try:

        await call.answer(
            "🔄 Mengecek pembayaran..."
        )

        # ====================================================
        # PURCHASE
        # ====================================================

        purchase = await fetchrow(
            """
            SELECT *
            FROM file_purchases
            WHERE payment_id=$1
            LIMIT 1
            """,
            invoice,
        )

        if not purchase:

            return await call.answer(
                "❌ Data pembayaran tidak ditemukan.",
                show_alert=True,
            )

        # ====================================================
        # SECURITY
        # ====================================================

        if int(
            purchase["user_id"]
        ) != int(
            call.from_user.id
        ):

            logger.warning(
                "UNAUTHORIZED PAYMENT CHECK | "
                "invoice=%s | user=%s",
                invoice,
                call.from_user.id,
            )

            return await call.answer(
                "❌ Pembayaran ini bukan milik kamu.",
                show_alert=True,
            )

        # ====================================================
        # ALREADY PAID
        # ====================================================

        if normalize_status(
            purchase["status"]
        ) == "paid":

            return await call.answer(
                "✅ Pembayaran sudah diproses.",
                show_alert=True,
            )

        # ====================================================
        # CHECK PROVIDER
        # ====================================================

        result = await BayarGG.check_payment(
            invoice
        )

        if not result:

            return await call.answer(
                "❌ Gagal mengecek pembayaran.",
                show_alert=True,
            )

        status = normalize_status(
            result.get("status")
            or result.get("payment_status")
        )

        logger.info(
            "BAYARGG CHECK | "
            "invoice=%s | status=%s",
            invoice,
            status,
        )

        # ====================================================
        # FAILED
        # ====================================================

        if status in FAILED_STATUSES:

            await execute(
                """
                UPDATE file_purchases
                SET status=$1
                WHERE id=$2
                  AND status='pending'
                """,
                status,
                purchase["id"],
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
        # FILE
        # ====================================================

        file = await fetchrow(
            """
            SELECT *
            FROM files
            WHERE code=$1
            """,
            purchase["file_code"],
        )

        if not file:

            return await call.answer(
                "❌ File tidak ditemukan.",
                show_alert=True,
            )

        # ====================================================
        # FINISH
        # ====================================================

        success = await finish_payment(
            call.bot,
            purchase,
            file,
            invoice,
            call.message,
        )

        if not success:

            return await call.answer(
                "⚠️ Pembayaran sudah diproses atau gagal diproses.",
                show_alert=True,
            )

    except Exception:

        logger.exception(
            "BAYARGG CHECK ERROR"
        )

        try:

            await call.message.answer(
                "❌ Terjadi kesalahan saat mengecek pembayaran."
            )

        except Exception:
            pass

    finally:

        CHECK_LOCK.discard(
            invoice
        )


# ============================================================
# CLOSE PAYMENT MENU
# ============================================================

@router.callback_query(
    F.data == "close"
)
async def close_payment(
    call: CallbackQuery,
):

    try:

        await call.message.delete()

    except Exception:
        pass

    await call.answer(
        "Pembayaran dibatalkan."
    )


# ============================================================
# MANUAL PAYMENT
# ============================================================

@router.callback_query(
    F.data.startswith("manual:")
)
async def manual_payment(
    call: CallbackQuery,
):

    code = call.data.split(
        ":",
        1,
    )[1]

    user_id = call.from_user.id

    # ========================================================
    # FILE
    # ========================================================

    file = await fetchrow(
        """
        SELECT *
        FROM files
        WHERE code=$1
        """,
        code,
    )

    if not file:

        return await call.answer(
            "❌ File tidak ditemukan.",
            show_alert=True,
        )

    price = int(
        file["price"] or 0
    )

    # ========================================================
    # CHECK EXISTING
    # ========================================================

    existing = await fetchrow(
        """
        SELECT *
        FROM file_purchases
        WHERE user_id=$1
          AND file_code=$2
          AND status='pending'
        ORDER BY id DESC
        LIMIT 1
        """,
        user_id,
        code,
    )

    # ========================================================
    # CREATE PURCHASE
    # ========================================================

    if not existing:

        payment_id = (
            f"MANUAL-{user_id}-{code}"
            f"-{secrets.token_hex(4)}"
        )

        try:

            existing = await fetchrow(
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
                RETURNING *
                """,
                user_id,
                code,
                file["owner_id"],
                price,
                payment_id,
            )

        except Exception:

            logger.exception(
                "MANUAL PURCHASE CREATE ERROR"
            )

            return await call.answer(
                "❌ Gagal membuat transaksi.",
                show_alert=True,
            )

    # ========================================================
    # CAPTION
    # ========================================================

    caption = (
        "📷 <b>PEMBAYARAN MANUAL</b>\n\n"
        f"📄 File:\n"
        f"<b>{file['title']}</b>\n\n"
        f"💰 Harga:\n"
        f"<b>{format_rupiah(price)}</b>\n\n"
        "Silahkan scan QR di atas.\n\n"
        "⚠️ Bayar sesuai nominal.\n"
        "Setelah membayar tekan tombol "
        "<b>Saya Sudah Bayar</b>."
    )

    # ========================================================
    # SEND QR
    # ========================================================

    try:

        msg = await call.message.answer_photo(
            MANUAL_QR_FILE_ID,
            caption=caption,
            parse_mode="HTML",
            reply_markup=manual_payment_keyboard(
                code
            ),
        )

        await execute(
            """
            UPDATE file_purchases
            SET
                qr_message_id=$1,
                qr_chat_id=$2
            WHERE id=$3
            """,
            msg.message_id,
            msg.chat.id,
            existing["id"],
        )

    except Exception:

        logger.exception(
            "MANUAL QR SEND ERROR"
        )

        return await call.answer(
            "❌ Gagal mengirim QR manual.",
            show_alert=True,
        )

    await call.answer(
        "Silahkan lakukan pembayaran."
    )


# ============================================================
# MANUAL PAYMENT CHECK REQUEST
# ============================================================

@router.callback_query(
    F.data.startswith("manualcheck:")
)
async def manual_check(
    call: CallbackQuery,
):

    code = call.data.split(
        ":",
        1,
    )[1]

    user_id = call.from_user.id

    # ========================================================
    # FILE
    # ========================================================

    file = await fetchrow(
        """
        SELECT *
        FROM files
        WHERE code=$1
        """,
        code,
    )

    if not file:

        return await call.answer(
            "❌ File tidak ditemukan.",
            show_alert=True,
        )

    # ========================================================
    # PURCHASE
    # ========================================================

    purchase = await fetchrow(
        """
        SELECT *
        FROM file_purchases
        WHERE user_id=$1
          AND file_code=$2
          AND status='pending'
        ORDER BY id DESC
        LIMIT 1
        """,
        user_id,
        code,
    )

    if not purchase:

        return await call.answer(
            "❌ Transaksi tidak ditemukan.",
            show_alert=True,
        )

    # ========================================================
    # ADMIN KEYBOARD
    # ========================================================

    text = (
        "📥 <b>MANUAL PAYMENT CHECK</b>\n\n"
        f"👤 User: <code>{user_id}</code>\n"
        f"📄 File: <b>{file['title']}</b>\n"
        f"🔑 Code: <code>{code}</code>\n"
        f"💰 Harga: <b>{format_rupiah(purchase['paid_price'])}</b>\n"
        f"🧾 ID: <code>{purchase['id']}</code>"
    )

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Approve",
                    callback_data=(
                        f"approve:{purchase['id']}"
                    ),
                )
            ],
            [
                InlineKeyboardButton(
                    text="❌ Reject",
                    callback_data=(
                        f"reject:{purchase['id']}"
                    ),
                )
            ],
        ]
    )

    # ========================================================
    # SEND TO ADMINS
    # ========================================================

    sent = 0

    for admin in ADMIN_IDS:

        try:

            await call.bot.send_message(
                admin,
                text,
                parse_mode="HTML",
                reply_markup=keyboard,
            )

            sent += 1

        except Exception:

            logger.exception(
                "SEND MANUAL ADMIN ERROR | admin=%s",
                admin,
            )

    if sent == 0:

        return await call.answer(
            "❌ Admin tidak dapat menerima permintaan.",
            show_alert=True,
        )

    await call.message.answer(
        "✅ Permintaan verifikasi pembayaran telah dikirim ke admin."
    )

    await call.answer(
        "Permintaan dikirim."
    )


# ============================================================
# APPROVE MANUAL
# ============================================================

@router.callback_query(
    F.data.startswith("approve:")
)
async def approve_manual(
    call: CallbackQuery,
):

    # ========================================================
    # ADMIN SECURITY
    # ========================================================

    if not is_admin(
        call.from_user.id
    ):

        return await call.answer(
            "❌ Kamu bukan admin.",
            show_alert=True,
        )

    purchase_id = int(
        call.data.split(
            ":",
            1,
        )[1]
    )

    # ========================================================
    # PURCHASE
    # ========================================================

    purchase = await fetchrow(
        """
        SELECT *
        FROM file_purchases
        WHERE id=$1
          AND status='pending'
        """,
        purchase_id,
    )

    if not purchase:

        return await call.answer(
            "❌ Pembelian tidak ditemukan / sudah diproses.",
            show_alert=True,
        )

    user_id = purchase["user_id"]
    code = purchase["file_code"]

    # ========================================================
    # FILE
    # ========================================================

    file = await fetchrow(
        """
        SELECT *
        FROM files
        WHERE code=$1
        """,
        code,
    )

    if not file:

        return await call.answer(
            "❌ File tidak ditemukan.",
            show_alert=True,
        )

    await call.answer(
        "⏳ Memproses pembayaran..."
    )

    # ========================================================
    # USER MESSAGE
    # ========================================================

    try:

        user_message = await call.bot.send_message(
            user_id,
            "⏳ Pembayaran sedang diproses...",
        )

    except Exception:

        logger.exception(
            "MANUAL USER MESSAGE ERROR"
        )

        return await call.answer(
            "❌ User belum pernah membuka bot.",
            show_alert=True,
        )

    # ========================================================
    # FINISH
    # ========================================================

    success = await finish_payment(
        call.bot,
        purchase,
        file,
        purchase["payment_id"],
        user_message,
    )

    if not success:

        return await call.answer(
            "❌ Pembayaran gagal diproses / sudah diproses.",
            show_alert=True,
        )

    # ========================================================
    # ADMIN MESSAGE
    # ========================================================

    try:

        await call.message.edit_text(
            (
                "✅ <b>PEMBAYARAN DISETUJUI</b>\n\n"
                f"👤 User: <code>{user_id}</code>\n"
                f"📦 File: <b>{file['title']}</b>\n"
                f"🔑 Code: <code>{code}</code>\n"
                f"💰 Harga: <b>{format_rupiah(purchase['paid_price'])}</b>"
            ),
            parse_mode="HTML",
        )

    except Exception:

        logger.warning(
            "EDIT APPROVE MESSAGE FAILED",
            exc_info=True,
        )


# ============================================================
# REJECT MANUAL
# ============================================================

@router.callback_query(
    F.data.startswith("reject:")
)
async def reject_manual(
    call: CallbackQuery,
):

    # ========================================================
    # ADMIN SECURITY
    # ========================================================

    if not is_admin(
        call.from_user.id
    ):

        return await call.answer(
            "❌ Kamu bukan admin.",
            show_alert=True,
        )

    purchase_id = int(
        call.data.split(
            ":",
            1,
        )[1]
    )

    # ========================================================
    # PURCHASE
    # ========================================================

    purchase = await fetchrow(
        """
        SELECT *
        FROM file_purchases
        WHERE id=$1
          AND status='pending'
        """,
        purchase_id,
    )

    if not purchase:

        return await call.answer(
            "❌ Pembelian tidak ditemukan / sudah diproses.",
            show_alert=True,
        )

    # ========================================================
    # ATOMIC REJECT
    # ========================================================

    rejected = await fetchrow(
        """
        UPDATE file_purchases
        SET status='rejected'
        WHERE id=$1
          AND status='pending'
        RETURNING *
        """,
        purchase_id,
    )

    if not rejected:

        return await call.answer(
            "❌ Pembayaran sudah diproses.",
            show_alert=True,
        )

    user_id = rejected["user_id"]
    code = rejected["file_code"]

    # ========================================================
    # NOTIFY USER
    # ========================================================

    try:

        await call.bot.send_message(
            user_id,
            (
                "❌ <b>Pembayaran Ditolak</b>\n\n"
                f"📦 File:\n"
                f"<code>{code}</code>\n\n"
                "Silahkan lakukan pembayaran ulang."
            ),
            parse_mode="HTML",
        )

    except Exception:

        logger.exception(
            "SEND REJECT USER ERROR"
        )

    # ========================================================
    # DELETE QR
    # ========================================================

    try:

        if (
            rejected.get("qr_message_id")
            and rejected.get("qr_chat_id")
        ):

            await call.bot.delete_message(
                chat_id=rejected["qr_chat_id"],
                message_id=rejected["qr_message_id"],
            )

    except Exception:

        pass

    # ========================================================
    # ADMIN MESSAGE
    # ========================================================

    try:

        await call.message.edit_text(
            (
                "❌ <b>PEMBAYARAN DITOLAK</b>\n\n"
                f"👤 User: <code>{user_id}</code>\n"
                f"📦 Code: <code>{code}</code>"
            ),
            parse_mode="HTML",
        )

    except Exception:

        pass

    await call.answer(
        "Pembayaran ditolak."
    )


# ============================================================
# CANCEL BAYARGG
# ============================================================

@router.callback_query(
    F.data.startswith("cancel:")
)
async def cancel_payment(
    call: CallbackQuery,
):

    invoice = call.data.split(
        ":",
        1,
    )[1]

    # ========================================================
    # PURCHASE
    # ========================================================

    payment = await fetchrow(
        """
        SELECT *
        FROM file_purchases
        WHERE payment_id=$1
        LIMIT 1
        """,
        invoice,
    )

    if not payment:

        return await call.answer(
            "❌ Data pembayaran tidak ditemukan.",
            show_alert=True,
        )

    # ========================================================
    # SECURITY
    # ========================================================

    if int(
        payment["user_id"]
    ) != int(
        call.from_user.id
    ):

        return await call.answer(
            "❌ Pembayaran ini bukan milik kamu.",
            show_alert=True,
        )

    # ========================================================
    # ALREADY PAID
    # ========================================================

    if normalize_status(
        payment["status"]
    ) == "paid":

        return await call.answer(
            "✅ Pembayaran sudah dibayar.",
            show_alert=True,
        )

    # ========================================================
    # PROVIDER CANCEL
    # ========================================================

    try:

        await BayarGG.cancel_payment(
            invoice
        )

    except Exception:

        logger.exception(
            "BAYARGG CANCEL ERROR"
        )

    # ========================================================
    # DATABASE CANCEL
    # ========================================================

    await execute(
        """
        UPDATE file_purchases
        SET status='cancel'
        WHERE id=$1
          AND status='pending'
        """,
        payment["id"],
    )

    # ========================================================
    # DELETE MEDIA SESSION
    # ========================================================

    await safe_delete(
        f"paidmedia:{invoice}"
    )

    # ========================================================
    # DELETE QR
    # ========================================================

    try:

        if (
            payment.get("qr_message_id")
            and payment.get("qr_chat_id")
        ):

            await call.bot.delete_message(
                chat_id=payment["qr_chat_id"],
                message_id=payment["qr_message_id"],
            )

    except Exception:

        logger.warning(
            "DELETE BAYARGG QR FAILED",
            exc_info=True,
        )

    await call.answer(
        "❌ Pembayaran dibatalkan."
    )

    try:

        await call.message.answer(
            "❌ <b>Pembayaran dibatalkan.</b>",
            parse_mode="HTML",
        )

    except Exception:
        pass


# ============================================================
# SEND PAGE MEDIA
# ============================================================

@router.callback_query(
    F.data.startswith("sp:")
)
async def send_page_media(
    call: CallbackQuery,
):

    _, media_id, page = call.data.split(
        ":"
    )

    page = int(page)

    data = await safe_get(
        f"paidmedia:{media_id}"
    )

    if not data:

        return await call.answer(
            "❌ Data media sudah expired.",
            show_alert=True,
        )

    media_list = data.get(
        "media",
        []
    )

    start = (
        page - 1
    ) * PER_PAGE

    end = (
        start + PER_PAGE
    )

    items = media_list[
        start:end
    ]

    if not items:

        return await call.answer(
            "❌ Halaman tidak ditemukan.",
            show_alert=True,
        )

    await call.answer(
        "📤 Mengirim file..."
    )

    sent = 0

    for item in items:

        try:

            await call.bot.copy_message(
                chat_id=call.from_user.id,
                from_chat_id=STORAGE_CHANNEL_ID,
                message_id=item["message_id"],
            )

            sent += 1

        except Exception:

            logger.exception(
                "SEND PAGE ERROR"
            )

    await call.message.answer(
        (
            f"✅ Halaman {page} selesai\n\n"
            f"📦 Terkirim: "
            f"{sent}/{len(items)} file"
        )
    )


# ============================================================
# SEND ALL MEDIA
# ============================================================

@router.callback_query(
    F.data.startswith("sa:")
)
async def send_all_media(
    call: CallbackQuery,
):

    _, media_id = call.data.split(
        ":"
    )

    data = await safe_get(
        f"paidmedia:{media_id}"
    )

    if not data:

        return await call.answer(
            "❌ Data media expired.",
            show_alert=True,
        )

    media_list = data.get(
        "media",
        []
    )

    if not media_list:

        return await call.answer(
            "❌ Media kosong.",
            show_alert=True,
        )

    await call.answer(
        "📦 Mengirim semua file..."
    )

    progress = await call.message.answer(
        f"⏳ Mengirim 0/{len(media_list)}"
    )

    sent = 0

    for index, item in enumerate(
        media_list,
        start=1,
    ):

        try:

            await call.bot.copy_message(
                chat_id=call.from_user.id,
                from_chat_id=STORAGE_CHANNEL_ID,
                message_id=item["message_id"],
            )

            sent += 1

            if index % 5 == 0:

                try:

                    await progress.edit_text(
                        f"⏳ Mengirim "
                        f"{index}/{len(media_list)}"
                    )

                except Exception:
                    pass

        except Exception:

            logger.exception(
                "SEND ALL ERROR"
            )

    try:

        await progress.edit_text(
            (
                "✅ Semua file selesai\n\n"
                f"📦 Berhasil: "
                f"{sent}/{len(media_list)}"
            )
        )

    except Exception:

        pass


# ============================================================
# MEDIA PAGE NAVIGATION
# ============================================================

@router.callback_query(
    F.data.startswith("mp:")
)
async def media_page(
    call: CallbackQuery,
):

    _, media_id, page = call.data.split(
        ":"
    )

    page = int(page)

    data = await safe_get(
        f"paidmedia:{media_id}"
    )

    if not data:

        return await call.answer(
            "❌ Session media sudah expired.",
            show_alert=True,
        )

    media_list = data.get(
        "media",
        []
    )

    if not media_list:

        return await call.answer(
            "❌ Media tidak ditemukan.",
            show_alert=True,
        )

    total = len(
        media_list
    )

    max_page = (
        total + PER_PAGE - 1
    ) // PER_PAGE

    if page < 1 or page > max_page:

        return await call.answer(
            "❌ Halaman tidak valid.",
            show_alert=True,
        )

    await call.message.edit_reply_markup(
        reply_markup=media_keyboard(
            media_id,
            page,
            total,
        )
    )

    await call.answer()


# ============================================================
# DISABLE "NONE" BUTTON
# ============================================================

@router.callback_query(
    F.data == "none"
)
async def none_callback(
    call: CallbackQuery,
):

    await call.answer()
