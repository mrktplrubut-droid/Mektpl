import asyncio
import html
import json
import logging
import secrets
from typing import Any

import aiohttp

from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    Message,
)

from database import fetchrow, fetch, execute
from utils.redis_client import safe_set, safe_get
from utils.cashi import Cashi

from config import (
    STORAGE_CHANNEL_ID,
    NOTIF_CHANNEL_ID,
    ADMIN_IDS,
    MANUAL_QR_FILE_ID,
    CASHI_API_KEY,
)

logger = logging.getLogger(__name__)
router = Router()


# ============================================================
# CONFIG
# ============================================================

PER_PAGE = 10
MEDIA_TTL = 3600

VERIFY_REQUEST_TTL = 300
CALLBACK_TOKEN_TTL = 900
CHECK_LOCK = 30

CASHI_BASE_URL = "https://cashi.id"
CASHI_CREATE_URL = f"{CASHI_BASE_URL}/api/create-order"

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
# FSM
# ============================================================

class RejectPaymentState(StatesGroup):
    waiting_reason = State()


# ============================================================
# BASIC HELPERS
# ============================================================

def mask_user_id(user_id: int) -> str:
    uid = str(user_id)

    if len(uid) <= 4:
        return "****"

    return uid[:2] + "****" + uid[-2:]


def format_rupiah(amount: Any) -> str:
    try:
        return f"Rp {int(amount):,}".replace(",", ".")
    except Exception:
        return f"Rp {amount}"


def normalize_status(value: Any) -> str:
    return str(value or "").strip().lower()


def clean_html(value: Any) -> str:
    return html.escape(str(value or ""))


def safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (ValueError, TypeError):
        return default


def get_admin_ids() -> set[int]:
    try:
        raw = ADMIN_IDS

        if raw is None:
            return set()

        if isinstance(raw, str):
            values = raw.replace(";", ",").split(",")

        elif isinstance(raw, (list, tuple, set)):
            values = raw

        else:
            values = [raw]

        result = set()

        for value in values:
            try:
                value = str(value).strip()

                if value:
                    result.add(int(value))

            except (ValueError, TypeError):
                continue

        return result

    except Exception:
        logger.exception("GET ADMIN IDS ERROR")
        return set()


def is_admin(user_id: int) -> bool:
    try:
        return int(user_id) in get_admin_ids()
    except Exception:
        return False


# ============================================================
# CALLBACK TOKEN
# ============================================================

async def create_callback_token(
    prefix: str,
    data: dict,
) -> str:

    token = secrets.token_urlsafe(10)

    await safe_set(
        f"cb:{prefix}:{token}",
        data,
        ex=CALLBACK_TOKEN_TTL,
    )

    return token


async def get_callback_token(
    prefix: str,
    token: str,
):

    if not token:
        return None

    try:
        return await safe_get(
            f"cb:{prefix}:{token}"
        )

    except Exception:
        logger.exception(
            "GET CALLBACK TOKEN ERROR | %s",
            prefix,
        )

        return None


# ============================================================
# MEDIA PARSER
# ============================================================

def parse_media(media_data: Any) -> list[dict]:

    if isinstance(media_data, str):

        try:
            media_data = json.loads(media_data)

        except Exception:
            logger.exception(
                "MEDIA JSON PARSE ERROR"
            )

            return []

    if not isinstance(media_data, list):
        return []

    result = []

    for item in media_data:

        if not isinstance(item, dict):
            continue

        message_id = item.get("message_id")

        try:
            message_id = int(message_id)

        except (ValueError, TypeError):
            continue

        if message_id <= 0:
            continue

        result.append({
            **item,
            "message_id": message_id,
        })

    return result


# ============================================================
# DATABASE
# ============================================================

async def get_file_by_code(code: str):

    if not code:
        return None

    code = str(code).strip()

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


async def get_purchase_by_id(
    purchase_id: int,
):

    return await fetchrow(
        """
        SELECT *
        FROM file_purchases
        WHERE id=$1
        LIMIT 1
        """,
        int(purchase_id),
    )


async def get_active_purchase(
    user_id: int,
    code: str,
):

    return await fetchrow(
        """
        SELECT *
        FROM file_purchases
        WHERE user_id=$1
          AND file_code=$2
          AND status='pending'
        ORDER BY id DESC
        LIMIT 1
        """,
        int(user_id),
        str(code).strip(),
    )


async def get_paid_purchase(
    user_id: int,
    code: str,
):

    return await fetchrow(
        """
        SELECT *
        FROM file_purchases
        WHERE user_id=$1
          AND file_code=$2
          AND status='paid'
        ORDER BY id DESC
        LIMIT 1
        """,
        int(user_id),
        str(code).strip(),
    )


# ============================================================
# PAYMENT KEYBOARD
# ============================================================

def payment_method_keyboard(
    code: str,
):

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="💳 Bayar via Cashi",
                    callback_data=f"cashi:{code}",
                )
            ],
            [
                InlineKeyboardButton(
                    text="📷 QR Manual",
                    callback_data=f"manual:{code}",
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


# ============================================================
# PAYMENT ENTRY
# ============================================================

@router.callback_query(
    F.data.startswith("pay:")
)
async def choose_payment(
    call: CallbackQuery,
):

    try:
        code = call.data.split(
            ":",
            1,
        )[1].strip()

    except (AttributeError, IndexError):

        return await call.answer(
            "❌ Code tidak valid.",
            show_alert=True,
        )

    if not code:

        return await call.answer(
            "❌ Code tidak valid.",
            show_alert=True,
        )

    file = await get_file_by_code(code)

    if not file:

        return await call.answer(
            "❌ File tidak ditemukan.",
            show_alert=True,
        )

    price = safe_int(file.get("price"))

    if price <= 0:

        return await call.answer(
            "❌ Harga file tidak valid.",
            show_alert=True,
        )

    user_id = int(call.from_user.id)

    # --------------------------------------------------------
    # ALREADY PAID
    # --------------------------------------------------------

    paid = await get_paid_purchase(
        user_id,
        code,
    )

    if paid:

        return await call.answer(
            "✅ Kamu sudah membeli file ini.",
            show_alert=True,
        )

    # --------------------------------------------------------
    # EXISTING ACTIVE TRANSACTION
    # --------------------------------------------------------

    existing = await get_active_purchase(
        user_id,
        code,
    )

    if existing:

        payment_id = str(
            existing.get("payment_id") or ""
        ).strip()

        # Cashi transaction
        if payment_id.startswith("CASHI-"):

            return await show_existing_cashi(
                call,
                existing,
                file,
            )

        # Manual transaction
        if payment_id.startswith("MANUAL-"):

            return await show_existing_manual(
                call,
                existing,
                file,
            )

    # --------------------------------------------------------
    # CHOOSE PAYMENT
    # --------------------------------------------------------

    await call.message.answer(
        (
            "💳 <b>PILIH METODE PEMBAYARAN</b>\n\n"
            f"📄 File:\n"
            f"<b>{clean_html(file.get('title'))}</b>\n\n"
            f"💰 Harga:\n"
            f"<b>{format_rupiah(price)}</b>\n\n"
            "Silakan pilih metode pembayaran:"
        ),
        parse_mode="HTML",
        reply_markup=payment_method_keyboard(code),
    )

    await call.answer()


# ============================================================
# CASHI ENTRY
# ============================================================

@router.callback_query(
    F.data.startswith("cashi:")
)
async def cashi_payment(
    call: CallbackQuery,
):

    try:
        code = call.data.split(
            ":",
            1,
        )[1].strip()

    except (AttributeError, IndexError):

        return await call.answer(
            "❌ Code tidak valid.",
            show_alert=True,
        )

    file = await get_file_by_code(code)

    if not file:

        return await call.answer(
            "❌ File tidak ditemukan.",
            show_alert=True,
        )

    price = safe_int(file.get("price"))

    if price <= 0:

        return await call.answer(
            "❌ Harga file tidak valid.",
            show_alert=True,
        )

    return await create_cashi_payment(
        call,
        code,
        file,
    )


# ============================================================
# MANUAL ENTRY
# ============================================================

@router.callback_query(
    F.data.startswith("manual:")
)
async def manual_payment(
    call: CallbackQuery,
):

    try:
        code = call.data.split(
            ":",
            1,
        )[1].strip()

    except (AttributeError, IndexError):

        return await call.answer(
            "❌ Code tidak valid.",
            show_alert=True,
        )

    file = await get_file_by_code(code)

    if not file:

        return await call.answer(
            "❌ File tidak ditemukan.",
            show_alert=True,
        )

    price = safe_int(file.get("price"))

    if price <= 0:

        return await call.answer(
            "❌ Harga file tidak valid.",
            show_alert=True,
        )

    return await create_manual_payment(
        call,
        code,
        file,
    )


# ============================================================
# CREATE / GET SINGLE PURCHASE
# ============================================================

async def get_or_create_purchase(
    user_id: int,
    code: str,
    file,
    payment_prefix: str,
):

    # --------------------------------------------------------
    # PAID
    # --------------------------------------------------------

    paid = await get_paid_purchase(
        user_id,
        code,
    )

    if paid:
        return {
            "purchase": paid,
            "already_paid": True,
        }

    # --------------------------------------------------------
    # EXISTING PENDING
    # --------------------------------------------------------

    existing = await get_active_purchase(
        user_id,
        code,
    )

    if existing:

        return {
            "purchase": existing,
            "already_paid": False,
            "existing": True,
        }

    # --------------------------------------------------------
    # CREATE ONE TRANSACTION
    # --------------------------------------------------------

    payment_id = (
        f"{payment_prefix}{user_id}-"
        f"{secrets.token_hex(8)}"
    )

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
            ON CONFLICT (user_id, file_code)
            DO UPDATE SET
                payment_id =
                    CASE
                        WHEN file_purchases.status='failed'
                        THEN EXCLUDED.payment_id
                        ELSE file_purchases.payment_id
                    END,

                status =
                    CASE
                        WHEN file_purchases.status='failed'
                        THEN 'pending'
                        ELSE file_purchases.status
                    END

            RETURNING *
            """,
            user_id,
            code,
            file.get("owner_id"),
            safe_int(file.get("price")),
            payment_id,
        )

    except Exception:

        logger.exception(
            "GET OR CREATE PURCHASE ERROR"
        )

        return None

    return {
        "purchase": purchase,
        "already_paid": False,
        "existing": False,
    }


# ============================================================
# CASHI API
# ============================================================

def cashi_headers() -> dict:

    return {
        "x-api-key": str(
            CASHI_API_KEY or ""
        ).strip(),

        "Content-Type": "application/json",

        "Accept": "application/json",
    }


async def cashi_create_order(
    amount: int,
    order_id: str,
):

    if not CASHI_API_KEY:

        logger.error(
            "CASHI_API_KEY BELUM DISET"
        )

        return None

    payload = {
        "amount": int(amount),
        "order_id": str(order_id),
        "kode_channel": "QRIS_CUSTOM",
    }

    try:

        timeout = aiohttp.ClientTimeout(
            total=30
        )

        async with aiohttp.ClientSession(
            timeout=timeout
        ) as session:

            async with session.post(
                CASHI_CREATE_URL,
                headers=cashi_headers(),
                json=payload,
            ) as response:

                raw_text = await response.text()

                try:
                    data = json.loads(
                        raw_text
                    )

                except Exception:

                    logger.error(
                        "CASHI INVALID JSON | HTTP=%s | BODY=%s",
                        response.status,
                        raw_text[:1000],
                    )

                    return None

                if (
                    response.status < 200
                    or response.status >= 300
                ):

                    logger.error(
                        "CASHI CREATE ERROR | HTTP=%s | RESPONSE=%s",
                        response.status,
                        data,
                    )

                    return None

                if not data.get("success"):

                    logger.error(
                        "CASHI CREATE FAILED | RESPONSE=%s",
                        data,
                    )

                    return None

                return data

    except asyncio.CancelledError:
        raise

    except Exception:

        logger.exception(
            "CASHI CREATE ORDER EXCEPTION"
        )

        return None


async def cashi_check_status(
    order_id: str,
):

    if not CASHI_API_KEY:
        return None

    order_id = str(
        order_id or ""
    ).strip()

    if not order_id:
        return None

    url = (
        f"{CASHI_BASE_URL}/api/check-status/"
        f"{order_id}"
    )

    try:

        timeout = aiohttp.ClientTimeout(
            total=20
        )

        async with aiohttp.ClientSession(
            timeout=timeout
        ) as session:

            async with session.get(
                url,
                headers=cashi_headers(),
            ) as response:

                raw_text = await response.text()

                try:
                    data = json.loads(
                        raw_text
                    )

                except Exception:

                    logger.error(
                        "CASHI STATUS INVALID JSON | HTTP=%s",
                        response.status,
                    )

                    return None

                if (
                    response.status < 200
                    or response.status >= 300
                ):

                    logger.error(
                        "CASHI STATUS HTTP ERROR | HTTP=%s | %s",
                        response.status,
                        data,
                    )

                    return None

                return data

    except asyncio.CancelledError:
        raise

    except Exception:

        logger.exception(
            "CASHI CHECK STATUS EXCEPTION"
        )

        return None


# ============================================================
# CASHI KEYBOARD
# ============================================================

async def payment_check_keyboard(
    code: str,
    payment_id: str,
):

    token = await create_callback_token(
        "paymentcheck",
        {
            "code": str(code).strip(),
            "payment_id": str(payment_id).strip(),
        },
    )

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔄 Cek Pembayaran",
                    callback_data=f"paymentcheck:{token}",
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


# ============================================================
# MANUAL KEYBOARD
# ============================================================

async def manual_payment_keyboard(
    code: str,
):

    token = await create_callback_token(
        "manualcheck",
        {
            "code": str(code).strip(),
        },
    )

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Saya Sudah Bayar",
                    callback_data=f"manualcheck:{token}",
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


# ============================================================
# EXISTING CASHI
# ============================================================

async def show_existing_cashi(
    call: CallbackQuery,
    purchase,
    file,
):

    payment_id = str(
        purchase.get("payment_id") or ""
    ).strip()

    if not payment_id:

        return await call.answer(
            "❌ ID pembayaran tidak valid.",
            show_alert=True,
        )

    status_data = await cashi_check_status(
        payment_id
    )

    if status_data:

        status = normalize_status(
            status_data.get("status")
        )

        if status in SUCCESS_STATUSES:

            return await process_existing_success(
                call,
                purchase,
                file,
            )

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

            # setelah expired/failed, user boleh memilih lagi
            return await call.message.answer(
                (
                    "⚠️ <b>Pembayaran Cashi sebelumnya gagal.</b>\n\n"
                    "Silakan pilih metode pembayaran baru."
                ),
                parse_mode="HTML",
                reply_markup=payment_method_keyboard(
                    file["code"]
                ),
            )

    qr_url = str(
        purchase.get("qr_image") or ""
    ).strip()

    payment_url = str(
        purchase.get("payment_url") or ""
    ).strip()

    keyboard = await payment_check_keyboard(
        file["code"],
        payment_id,
    )

    price = safe_int(
        file.get("price")
    )

    if qr_url:

        try:

            await call.message.answer_photo(
                photo=qr_url,
                caption=(
                    "💳 <b>PEMBAYARAN CASHI</b>\n\n"
                    f"📄 <b>{clean_html(file.get('title'))}</b>\n\n"
                    f"💰 <b>{format_rupiah(price)}</b>\n\n"
                    "Scan QR di atas.\n"
                    "Setelah membayar, tekan "
                    "<b>🔄 Cek Pembayaran</b>."
                ),
                parse_mode="HTML",
                reply_markup=keyboard,
            )

        except Exception:

            logger.exception(
                "SEND EXISTING CASHI QR ERROR"
            )

    elif payment_url:

        await call.message.answer(
            (
                "💳 <b>PEMBAYARAN CASHI</b>\n\n"
                f"📄 <b>{clean_html(file.get('title'))}</b>\n"
                f"💰 <b>{format_rupiah(price)}</b>\n\n"
                "Silakan lanjutkan pembayaran."
            ),
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="💳 Bayar Sekarang",
                            url=payment_url,
                        )
                    ],
                    [
                        keyboard.inline_keyboard[0][0]
                    ],
                    [
                        InlineKeyboardButton(
                            text="❌ Batal",
                            callback_data="close",
                        )
                    ],
                ]
            ),
        )

    else:

        await call.message.answer(
            "⚠️ Data pembayaran Cashi tidak memiliki QR/link.",
            reply_markup=keyboard,
        )

    return await call.answer(
        "⏳ Transaksi masih aktif.",
        show_alert=True,
    )


# ============================================================
# EXISTING MANUAL
# ============================================================

async def show_existing_manual(
    call: CallbackQuery,
    purchase,
    file,
):

    if not MANUAL_QR_FILE_ID:

        return await call.answer(
            "❌ QR manual sedang tidak tersedia.",
            show_alert=True,
        )

    keyboard = await manual_payment_keyboard(
        file["code"]
    )

    price = safe_int(
        file.get("price")
    )

    try:

        msg = await call.message.answer_photo(
            photo=MANUAL_QR_FILE_ID,
            caption=(
                "📷 <b>PEMBAYARAN MANUAL</b>\n\n"
                f"📄 <b>{clean_html(file.get('title'))}</b>\n\n"
                f"💰 Harga:\n"
                f"<b>{format_rupiah(price)}</b>\n\n"
                "Scan QR manual di atas.\n\n"
                "Setelah pembayaran, tekan "
                "<b>✅ Saya Sudah Bayar</b>."
            ),
            parse_mode="HTML",
            reply_markup=keyboard,
        )

        await execute(
            """
            UPDATE file_purchases
            SET
                qr_message_id=$1,
                qr_chat_id=$2
            WHERE id=$3
              AND status='pending'
            """,
            msg.message_id,
            msg.chat.id,
            purchase["id"],
        )

    except Exception:

        logger.exception(
            "SEND EXISTING MANUAL ERROR"
        )

    return await call.answer(
        "⏳ Transaksi manual masih aktif.",
        show_alert=True,
    )


# ============================================================
# CREATE CASHI PAYMENT
# ============================================================

async def create_cashi_payment(
    call: CallbackQuery,
    code: str,
    file,
):

    user_id = int(
        call.from_user.id
    )

    price = safe_int(
        file.get("price")
    )

    # --------------------------------------------------------
    # ALREADY PAID
    # --------------------------------------------------------

    paid = await get_paid_purchase(
        user_id,
        code,
    )

    if paid:

        return await call.answer(
            "✅ Kamu sudah membeli file ini.",
            show_alert=True,
        )

    # --------------------------------------------------------
    # EXISTING TRANSACTION
    # --------------------------------------------------------

    existing = await get_active_purchase(
        user_id,
        code,
    )

    if existing:

        payment_id = str(
            existing.get("payment_id") or ""
        ).strip()

        if payment_id.startswith("MANUAL-"):

            return await call.answer(
                "⏳ Kamu sudah memiliki pembayaran manual aktif untuk file ini.",
                show_alert=True,
            )

        if payment_id.startswith("CASHI-"):

            return await show_existing_cashi(
                call,
                existing,
                file,
            )

    # --------------------------------------------------------
    # CREATE ONE PURCHASE
    # --------------------------------------------------------

    result = await get_or_create_purchase(
        user_id=user_id,
        code=code,
        file=file,
        payment_prefix="CASHI-",
    )

    if not result:

        return await call.answer(
            "❌ Gagal membuat transaksi.",
            show_alert=True,
        )

    purchase = result["purchase"]

    if result.get("already_paid"):

        return await call.answer(
            "✅ Kamu sudah membeli file ini.",
            show_alert=True,
        )

    # Race condition protection:
    # another request may have created the transaction.
    payment_id = str(
        purchase.get("payment_id") or ""
    ).strip()

    if not payment_id.startswith("CASHI-"):

        if payment_id.startswith("MANUAL-"):

            return await call.answer(
                "⏳ Pembayaran manual untuk file ini sudah aktif.",
                show_alert=True,
            )

    await call.answer(
        "⏳ Membuat pembayaran Cashi..."
    )

    # --------------------------------------------------------
    # CASHI CREATE
    # --------------------------------------------------------

    cashi = await cashi_create_order(
        amount=price,
        order_id=payment_id,
    )

    if not cashi:

        # IMPORTANT:
        # Jangan membuat purchase baru.
        # Ubah purchase yang sama menjadi manual.
        if MANUAL_QR_FILE_ID:

            manual_payment_id = (
                f"MANUAL-{user_id}-"
                f"{secrets.token_hex(8)}"
            )

            converted = await fetchrow(
                """
                UPDATE file_purchases
                SET
                    payment_id=$1,
                    status='pending',
                    qr_image=NULL,
                    payment_url=NULL,
                    expires_at=NULL
                WHERE id=$2
                  AND status='pending'
                  AND payment_id=$3
                RETURNING *
                """,
                manual_payment_id,
                purchase["id"],
                payment_id,
            )

            if converted:

                return await send_manual_payment(
                    call,
                    converted,
                    file,
                )

        await execute(
            """
            UPDATE file_purchases
            SET status='failed'
            WHERE id=$1
              AND status='pending'
            """,
            purchase["id"],
        )

        return await call.message.answer(
            (
                "❌ <b>Pembayaran Cashi gagal dibuat.</b>\n\n"
                "Silakan coba beberapa saat lagi."
            ),
            parse_mode="HTML",
            reply_markup=payment_method_keyboard(
                code
            ),
        )

    # --------------------------------------------------------
    # CASHI DATA
    # --------------------------------------------------------

    cashi_order_id = str(
        cashi.get("orderId")
        or cashi.get("order_id")
        or payment_id
    ).strip()

    qr_url = str(
        cashi.get("qrUrl")
        or ""
    ).strip()

    checkout_url = str(
        cashi.get("checkout_url")
        or ""
    ).strip()

    expires_at = Cashi._parse_datetime(
        cashi.get("expires_at")
    )

    # --------------------------------------------------------
    # SAVE CASHI
    # --------------------------------------------------------

    saved = await fetchrow(
        """
        UPDATE file_purchases
        SET
            payment_id=$1,
            qr_image=$2,
            payment_url=$3,
            expires_at=$4
        WHERE id=$5
          AND status='pending'
        RETURNING *
        """,
        cashi_order_id,
        qr_url or None,
        checkout_url or None,
        expires_at,
        purchase["id"],
    )

    if not saved:

        logger.error(
            "CASHI PURCHASE SAVE FAILED | purchase=%s",
            purchase["id"],
        )

        return await call.message.answer(
            "❌ Gagal menyimpan pembayaran Cashi.",
        )

    keyboard = await payment_check_keyboard(
        code,
        cashi_order_id,
    )

    caption = (
        "💳 <b>PEMBAYARAN CASHI</b>\n\n"
        f"📄 File:\n"
        f"<b>{clean_html(file.get('title'))}</b>\n\n"
        f"🔑 Code:\n"
        f"<code>{clean_html(code)}</code>\n\n"
        f"💰 Harga:\n"
        f"<b>{format_rupiah(price)}</b>\n\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "📌 <b>Cara Pembayaran</b>\n\n"
        "1️⃣ Scan QR Cashi\n"
        "2️⃣ Bayar sesuai nominal\n"
        "3️⃣ Tunggu pembayaran berhasil\n"
        "4️⃣ Tekan <b>🔄 Cek Pembayaran</b>\n\n"
        "⚡ Pembayaran diverifikasi otomatis.\n"
        "⚠️ Jangan melakukan pembayaran dua kali."
    )

    try:

        msg = None

        if qr_url:

            msg = await call.message.answer_photo(
                photo=qr_url,
                caption=caption,
                parse_mode="HTML",
                reply_markup=keyboard,
            )

        elif checkout_url:

            check_callback = (
                keyboard
                .inline_keyboard[0][0]
                .callback_data
            )

            msg = await call.message.answer(
                (
                    f"{caption}\n\n"
                    "👇 Klik <b>Bayar Sekarang</b>."
                ),
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            InlineKeyboardButton(
                                text="💳 Bayar Sekarang",
                                url=checkout_url,
                            )
                        ],
                        [
                            InlineKeyboardButton(
                                text="🔄 Cek Pembayaran",
                                callback_data=check_callback,
                            )
                        ],
                        [
                            InlineKeyboardButton(
                                text="❌ Batal",
                                callback_data="close",
                            )
                        ],
                    ]
                ),
            )

        else:

            msg = await call.message.answer(
                caption,
                parse_mode="HTML",
                reply_markup=keyboard,
            )

        if msg:

            await execute(
                """
                UPDATE file_purchases
                SET
                    qr_message_id=$1,
                    qr_chat_id=$2
                WHERE id=$3
                  AND status='pending'
                """,
                msg.message_id,
                msg.chat.id,
                saved["id"],
            )

    except Exception:

        logger.exception(
            "SEND CASHI PAYMENT ERROR"
        )

        return await call.message.answer(
            (
                "⚠️ Pembayaran Cashi sudah dibuat, "
                "tetapi QR gagal dikirim."
            ),
            parse_mode="HTML",
        )


# ============================================================
# CREATE MANUAL PAYMENT
# ============================================================

async def create_manual_payment(
    call: CallbackQuery,
    code: str,
    file,
):

    if not MANUAL_QR_FILE_ID:

        return await call.answer(
            "❌ QR manual belum dikonfigurasi.",
            show_alert=True,
        )

    user_id = int(
        call.from_user.id
    )

    # --------------------------------------------------------
    # ALREADY PAID
    # --------------------------------------------------------

    paid = await get_paid_purchase(
        user_id,
        code,
    )

    if paid:

        return await call.answer(
            "✅ Kamu sudah membeli file ini.",
            show_alert=True,
        )

    # --------------------------------------------------------
    # EXISTING
    # --------------------------------------------------------

    existing = await get_active_purchase(
        user_id,
        code,
    )

    if existing:

        payment_id = str(
            existing.get("payment_id") or ""
        ).strip()

        if payment_id.startswith("CASHI-"):

            return await call.answer(
                (
                    "⏳ Kamu sudah memiliki pembayaran "
                    "Cashi aktif untuk file ini."
                ),
                show_alert=True,
            )

        if payment_id.startswith("MANUAL-"):

            return await show_existing_manual(
                call,
                existing,
                file,
            )

    # --------------------------------------------------------
    # CREATE SINGLE MANUAL TRANSACTION
    # --------------------------------------------------------

    result = await get_or_create_purchase(
        user_id=user_id,
        code=code,
        file=file,
        payment_prefix="MANUAL-",
    )

    if not result:

        return await call.answer(
            "❌ Gagal membuat transaksi.",
            show_alert=True,
        )

    purchase = result["purchase"]

    if result.get("already_paid"):

        return await call.answer(
            "✅ Kamu sudah membeli file ini.",
            show_alert=True,
        )

    payment_id = str(
        purchase.get("payment_id") or ""
    ).strip()

    if payment_id.startswith("CASHI-"):

        return await call.answer(
            "⏳ Pembayaran Cashi untuk file ini sudah aktif.",
            show_alert=True,
        )

    return await send_manual_payment(
        call,
        purchase,
        file,
    )


# ============================================================
# SEND MANUAL PAYMENT
# ============================================================

async def send_manual_payment(
    call: CallbackQuery,
    purchase,
    file,
):

    if not MANUAL_QR_FILE_ID:

        return await call.message.answer(
            "❌ QR manual belum tersedia."
        )

    code = str(
        file.get("code") or ""
    ).strip()

    price = safe_int(
        file.get("price")
    )

    keyboard = await manual_payment_keyboard(
        code
    )

    try:

        msg = await call.message.answer_photo(
            photo=MANUAL_QR_FILE_ID,
            caption=(
                "📷 <b>PEMBAYARAN MANUAL</b>\n\n"
                f"📄 File:\n"
                f"<b>{clean_html(file.get('title'))}</b>\n\n"
                f"🔑 Code:\n"
                f"<code>{clean_html(code)}</code>\n\n"
                f"💰 Harga:\n"
                f"<b>{format_rupiah(price)}</b>\n\n"
                "━━━━━━━━━━━━━━━━━━\n"
                "📌 <b>Cara Pembayaran</b>\n\n"
                "1️⃣ Scan QR manual\n"
                "2️⃣ Bayar sesuai nominal\n"
                "3️⃣ Pastikan pembayaran berhasil\n"
                "4️⃣ Tekan <b>✅ Saya Sudah Bayar</b>\n\n"
                "⚠️ Setelah menekan tombol, admin akan "
                "memverifikasi pembayaran."
            ),
            parse_mode="HTML",
            reply_markup=keyboard,
        )

        await execute(
            """
            UPDATE file_purchases
            SET
                qr_message_id=$1,
                qr_chat_id=$2
            WHERE id=$3
              AND status='pending'
            """,
            msg.message_id,
            msg.chat.id,
            purchase["id"],
        )

    except Exception:

        logger.exception(
            "SEND MANUAL PAYMENT ERROR"
        )

        return await call.message.answer(
            "❌ Gagal mengirim QR manual."
        )


# ============================================================
# PAYMENT CHECK CALLBACK
# ============================================================

@router.callback_query(
    F.data.startswith("paymentcheck:")
)
async def check_cashi_payment(
    call: CallbackQuery,
):

    try:

        token = call.data.split(
            ":",
            1,
        )[1].strip()

    except (AttributeError, IndexError):

        return await call.answer(
            "❌ Permintaan tidak valid.",
            show_alert=True,
        )

    data = await get_callback_token(
        "paymentcheck",
        token,
    )

    if not data:

        return await call.answer(
            "❌ Tombol sudah expired.",
            show_alert=True,
        )

    code = str(
        data.get("code") or ""
    ).strip()

    payment_id = str(
        data.get("payment_id") or ""
    ).strip()

    if not code or not payment_id:

        return await call.answer(
            "❌ Data pembayaran tidak valid.",
            show_alert=True,
        )

    user_id = int(
        call.from_user.id
    )

    lock_key = (
        f"cashi-check:"
        f"{user_id}:"
        f"{payment_id}"
    )

    try:

        if await safe_get(lock_key):

            return await call.answer(
                "⏳ Pembayaran sedang dicek...",
                show_alert=True,
            )

        await safe_set(
            lock_key,
            True,
            ex=CHECK_LOCK,
        )

    except Exception:

        logger.warning(
            "CASHI CHECK LOCK ERROR",
            exc_info=True,
        )

    await call.answer(
        "🔄 Mengecek pembayaran Cashi..."
    )

    # --------------------------------------------------------
    # FIND EXACT PURCHASE
    # --------------------------------------------------------

    purchase = await fetchrow(
        """
        SELECT *
        FROM file_purchases
        WHERE user_id=$1
          AND file_code=$2
          AND payment_id=$3
        LIMIT 1
        """,
        user_id,
        code,
        payment_id,
    )

    if not purchase:

        return await call.message.answer(
            "❌ Transaksi tidak ditemukan."
        )

    # --------------------------------------------------------
    # ALREADY PAID
    # --------------------------------------------------------

    if normalize_status(
        purchase.get("status")
    ) == "paid":

        return await call.message.answer(
            "✅ Pembayaran ini sudah berhasil diproses."
        )

    if not payment_id.startswith("CASHI-"):

        return await call.answer(
            "❌ Ini bukan transaksi Cashi.",
            show_alert=True,
        )

    # --------------------------------------------------------
    # CASHI STATUS
    # --------------------------------------------------------

    status_data = await cashi_check_status(
        payment_id
    )

    if not status_data:

        return await call.message.answer(
            (
                "⚠️ <b>Cashi belum dapat dihubungi.</b>\n\n"
                "Silakan coba lagi beberapa saat."
            ),
            parse_mode="HTML",
        )

    status = normalize_status(
        status_data.get("status")
    )

    logger.info(
        "CASHI STATUS | payment=%s | status=%s | response=%s",
        payment_id,
        status,
        status_data,
    )

    # --------------------------------------------------------
    # SUCCESS
    # --------------------------------------------------------

    if status in SUCCESS_STATUSES:

        file = await get_file_by_code(
            code
        )

        if not file:

            return await call.message.answer(
                "❌ File transaksi tidak ditemukan."
            )

        return await process_existing_success(
            call,
            purchase,
            file,
        )

    # --------------------------------------------------------
    # FAILED
    # --------------------------------------------------------

    if status in FAILED_STATUSES:

        changed = await fetchrow(
            """
            UPDATE file_purchases
            SET status=$1
            WHERE id=$2
              AND status='pending'
            RETURNING *
            """,
            status,
            purchase["id"],
        )

        if not changed:

            return await call.message.answer(
                "⚠️ Transaksi sudah diproses."
            )

        return await call.message.answer(
            (
                "❌ <b>Pembayaran tidak berhasil.</b>\n\n"
                f"Status Cashi: "
                f"<code>{clean_html(status.upper())}</code>\n\n"
                "Silakan pilih pembayaran baru."
            ),
            parse_mode="HTML",
            reply_markup=payment_method_keyboard(
                code
            ),
        )

    # --------------------------------------------------------
    # PENDING
    # --------------------------------------------------------

    return await call.message.answer(
        (
            "⏳ <b>Pembayaran belum terkonfirmasi.</b>\n\n"
            "Cashi belum memberikan status berhasil.\n\n"
            "Jika sudah membayar, tunggu beberapa detik "
            "lalu tekan <b>🔄 Cek Pembayaran</b> lagi."
        ),
        parse_mode="HTML",
    )


# ============================================================
# EXISTING SUCCESS
# ============================================================

async def process_existing_success(
    call: CallbackQuery,
    purchase,
    file,
):

    user_id = safe_int(
        purchase.get("user_id")
    )

    try:

        user_message = await call.bot.send_message(
            user_id,
            "⏳ Pembayaran berhasil terdeteksi. Memproses file...",
        )

    except Exception:

        logger.exception(
            "SEND SUCCESS MESSAGE ERROR"
        )

        return False

    return await finish_payment(
        call.bot,
        purchase,
        file,
        purchase.get("payment_id"),
        user_message,
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

    purchase_id = safe_int(
        purchase.get("id")
    )

    if purchase_id <= 0:
        return False

    try:

        media_list = parse_media(
            file.get("media")
        )

        if not media_list:

            await message.answer(
                "❌ Media file kosong."
            )

            return False

        # ====================================================
        # ATOMIC PAYMENT
        # ====================================================
        #
        # Hanya satu proses yang bisa mengubah:
        # pending -> paid
        #
        # Jika admin approve dan Cashi success bersamaan,
        # salah satunya menang dan satunya gagal.
        #

        updated = await fetchrow(
            """
            UPDATE file_purchases
            SET
                status='paid',
                paid_at=COALESCE(
                    paid_at,
                    NOW()
                )
            WHERE id=$1
              AND status='pending'
            RETURNING *
            """,
            purchase_id,
        )

        if not updated:

            logger.info(
                "PAYMENT ALREADY PROCESSED | purchase=%s",
                purchase_id,
            )

            # Jangan kirim media dua kali.
            try:

                current = await get_purchase_by_id(
                    purchase_id
                )

                if current and current.get("status") == "paid":

                    await message.answer(
                        "ℹ️ Pembayaran ini sudah diproses sebelumnya."
                    )

            except Exception:
                pass

            return False

        purchase = updated

        # ====================================================
        # MEDIA SESSION
        # ====================================================

        media_id = secrets.token_hex(16)

        session_data = {
            "user_id": int(
                purchase["user_id"]
            ),
            "media": media_list,
            "share_media": bool(
                file.get("share_media", False)
            ),
            "invoice": invoice,
            "purchase_id": purchase_id,
        }

        await safe_set(
            f"paidmedia:{media_id}",
            session_data,
            ex=MEDIA_TTL,
        )

        await execute(
            """
            UPDATE file_purchases
            SET media_session_id=$1
            WHERE id=$2
            """,
            media_id,
            purchase_id,
        )

        # ====================================================
        # BUY COUNT
        # ====================================================

        try:

            await execute(
                """
                UPDATE files
                SET
                    buy_count=COALESCE(
                        buy_count,
                        0
                    ) + 1,

                    sold=COALESCE(
                        sold,
                        0
                    ) + 1

                WHERE code=$1
                """,
                file["code"],
            )

        except Exception:

            logger.exception(
                "BUY COUNT UPDATE ERROR"
            )

        # ====================================================
        # FREE CODE PROGRESS
        # ====================================================

        try:

            completed_rows = await fetch(
                """
                UPDATE free_code_progress
                SET
                    purchase_count=LEAST(
                        3,
                        COALESCE(
                            purchase_count,
                            0
                        ) + 1
                    ),

                    completed=(
                        LEAST(
                            3,
                            COALESCE(
                                purchase_count,
                                0
                            ) + 1
                        ) >= 3
                    ),

                    completed_at=CASE
                        WHEN LEAST(
                            3,
                            COALESCE(
                                purchase_count,
                                0
                            ) + 1
                        ) >= 3
                        THEN COALESCE(
                            completed_at,
                            NOW()
                        )
                        ELSE completed_at
                    END

                WHERE code=$1
                  AND user_id=$2
                  AND completed=FALSE

                RETURNING
                    user_id,
                    purchase_count,
                    completed
                """,
                file["code"],
                purchase["user_id"],
            )

            for row in completed_rows:

                if row["completed"]:

                    try:

                        await bot.send_message(
                            row["user_id"],
                            (
                                "🎉 <b>Progress Code Free 3/3!</b>\n\n"
                                f"Code "
                                f"<code>{clean_html(file['code'])}</code>\n"
                                "sudah mencapai 3 pembelian berhasil.\n\n"
                                "🔓 Code sekarang bisa dibuka gratis."
                            ),
                            parse_mode="HTML",
                        )

                    except Exception:

                        logger.exception(
                            "FREE PROGRESS NOTIFY ERROR"
                        )

        except Exception:

            logger.exception(
                "FREE CODE PROGRESS UPDATE ERROR"
            )

        # ====================================================
        # SELLER PROFIT
        # ====================================================

        try:

            price = safe_int(
                file.get("price")
            )

            income = int(
                price * 0.5
            )

            owner_id = file.get(
                "owner_id"
            )

            if owner_id and income > 0:

                await execute(
                    """
                    UPDATE users
                    SET
                        balance=COALESCE(
                            balance,
                            0
                        ) + $1,

                        total_earn=COALESCE(
                            total_earn,
                            0
                        ) + $1

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
                    ($1,$2,$3,$4)
                    """,
                    owner_id,
                    "file_sale",
                    income,
                    f"Pendapatan file {file['code']}",
                )

        except Exception:

            logger.exception(
                "SELLER PROFIT ERROR"
            )

        # ====================================================
        # CHANNEL NOTIFICATION
        # ====================================================

        try:

            if NOTIF_CHANNEL_ID:

                masked = mask_user_id(
                    purchase["user_id"]
                )

                buy_url = (
                    "https://t.me/mktplbot"
                    f"?start={file['code']}"
                )

                keyboard = InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            InlineKeyboardButton(
                                text="🛒 Buy Now",
                                url=buy_url,
                            )
                        ]
                    ]
                )

                await bot.send_message(
                    NOTIF_CHANNEL_ID,
                    (
                        "💸 <b>FILE PAYMENT SUCCESS</b>\n\n"
                        f"📄 Judul: "
                        f"<b>{clean_html(file.get('title'))}</b>\n"
                        f"📁 Code: "
                        f"<code>{clean_html(file.get('code'))}</code>\n"
                        f"👤 User: "
                        f"<code>{masked}</code>\n"
                        f"💰 Harga: "
                        f"<b>{format_rupiah(purchase.get('paid_price'))}</b>\n"
                        "💳 Payment: <b>"
                        f"{'CASHI' if str(purchase.get('payment_id', '')).startswith('CASHI-') else 'MANUAL'}"
                        "</b>"
                    ),
                    parse_mode="HTML",
                    reply_markup=keyboard,
                )

        except Exception:

            logger.exception(
                "PAYMENT NOTIFICATION ERROR"
            )

        # ====================================================
        # DELETE PAYMENT QR
        # ====================================================

        try:

            qr_message_id = purchase.get(
                "qr_message_id"
            )

            qr_chat_id = purchase.get(
                "qr_chat_id"
            )

            if qr_message_id and qr_chat_id:

                await bot.delete_message(
                    chat_id=int(qr_chat_id),
                    message_id=int(qr_message_id),
                )

        except Exception:

            logger.warning(
                "DELETE PAYMENT QR FAILED",
                exc_info=True,
            )

        # ====================================================
        # MEDIA MENU
        # ====================================================

        total = len(
            media_list
        )

        await message.answer(
            (
                "🎉 <b>Pembayaran berhasil!</b>\n\n"
                f"📦 Total File: <b>{total}</b>\n\n"
                "Silakan pilih pengiriman:"
            ),
            parse_mode="HTML",
            reply_markup=media_keyboard(
                media_id,
                1,
                total,
            ),
        )

        logger.info(
            "PAYMENT FINISHED | purchase=%s | user=%s | code=%s",
            purchase_id,
            purchase["user_id"],
            file["code"],
        )

        return True

    except Exception:

        logger.exception(
            "FINISH PAYMENT ERROR | purchase=%s",
            purchase_id,
        )

        return False


# ============================================================
# MANUAL PAYMENT CHECK
# ============================================================

@router.callback_query(
    F.data.startswith("manualcheck:")
)
async def manual_check(
    call: CallbackQuery,
):

    try:

        token = call.data.split(
            ":",
            1,
        )[1].strip()

    except (AttributeError, IndexError):

        return await call.answer(
            "❌ Permintaan tidak valid.",
            show_alert=True,
        )

    callback_data = await get_callback_token(
        "manualcheck",
        token,
    )

    if not callback_data:

        return await call.answer(
            "❌ Tombol sudah expired.",
            show_alert=True,
        )

    code = str(
        callback_data.get("code") or ""
    ).strip()

    user_id = int(
        call.from_user.id
    )

    purchase = await get_active_purchase(
        user_id,
        code,
    )

    if not purchase:

        paid = await get_paid_purchase(
            user_id,
            code,
        )

        if paid:

            return await call.answer(
                "✅ Pembayaran sudah diverifikasi.",
                show_alert=True,
            )

        return await call.answer(
            "❌ Transaksi tidak ditemukan.",
            show_alert=True,
        )

    payment_id = str(
        purchase.get("payment_id") or ""
    ).strip()

    if not payment_id.startswith("MANUAL-"):

        return await call.answer(
            "❌ Transaksi ini bukan pembayaran manual.",
            show_alert=True,
        )

    purchase_id = safe_int(
        purchase.get("id")
    )

    lock_key = (
        f"manualverify:{purchase_id}"
    )

    try:

        if await safe_get(lock_key):

            return await call.answer(
                "⏳ Permintaan verifikasi sudah dikirim.",
                show_alert=True,
            )

        await safe_set(
            lock_key,
            True,
            ex=VERIFY_REQUEST_TTL,
        )

    except Exception:

        logger.warning(
            "MANUAL VERIFY LOCK ERROR",
            exc_info=True,
        )

    file = await get_file_by_code(
        code
    )

    if not file:

        return await call.answer(
            "❌ File tidak ditemukan.",
            show_alert=True,
        )

    text = (
        "📥 <b>MANUAL PAYMENT CHECK</b>\n\n"
        f"👤 User: <code>{user_id}</code>\n"
        f"📄 File: <b>{clean_html(file.get('title'))}</b>\n"
        f"🔑 Code: <code>{clean_html(code)}</code>\n"
        f"💰 Harga: "
        f"<b>{format_rupiah(purchase.get('paid_price'))}</b>\n"
        f"🧾 ID: <code>{purchase_id}</code>\n"
        f"💳 Payment: "
        f"<code>{clean_html(payment_id)}</code>"
    )

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Approve",
                    callback_data=f"approve:{purchase_id}",
                ),
                InlineKeyboardButton(
                    text="❌ Reject",
                    callback_data=f"reject:{purchase_id}",
                ),
            ]
        ]
    )

    sent = 0

    for admin_id in get_admin_ids():

        try:

            await call.bot.send_message(
                admin_id,
                text,
                parse_mode="HTML",
                reply_markup=keyboard,
            )

            sent += 1

        except Exception:

            logger.exception(
                "SEND MANUAL ADMIN ERROR"
            )

    if sent == 0:

        return await call.message.answer(
            "❌ Admin tidak dapat menerima permintaan."
        )

    await call.message.answer(
        (
            "✅ <b>Permintaan verifikasi dikirim.</b>\n\n"
            "⏳ Tunggu admin memeriksa pembayaran."
        ),
        parse_mode="HTML",
    )


# ============================================================
# APPROVE MANUAL
# ============================================================

@router.callback_query(
    F.data.startswith("approve:")
)
async def approve_manual(
    call: CallbackQuery,
    state: FSMContext,
):

    if not is_admin(
        call.from_user.id
    ):

        return await call.answer(
            "❌ Kamu bukan admin.",
            show_alert=True,
        )

    await state.clear()

    try:

        purchase_id = int(
            call.data.split(
                ":",
                1,
            )[1]
        )

    except (ValueError, IndexError):

        return await call.answer(
            "❌ ID transaksi tidak valid.",
            show_alert=True,
        )

    # --------------------------------------------------------
    # ATOMIC CLAIM
    # --------------------------------------------------------

    purchase = await fetchrow(
        """
        UPDATE file_purchases
        SET
            status='verifying'
        WHERE id=$1
          AND status='pending'
          AND payment_id LIKE 'MANUAL-%'
        RETURNING *
        """,
        purchase_id,
    )

    if not purchase:

        # Bisa berarti sudah approved/rejected
        current = await get_purchase_by_id(
            purchase_id
        )

        if current and current.get("status") == "paid":

            return await call.answer(
                "✅ Pembayaran sudah diproses admin lain.",
                show_alert=True,
            )

        if current and current.get("status") == "rejected":

            return await call.answer(
                "❌ Pembayaran sudah ditolak.",
                show_alert=True,
            )

        return await call.answer(
            "❌ Transaksi sudah diproses / tidak valid.",
            show_alert=True,
        )

    file = await get_file_by_code(
        purchase["file_code"]
    )

    if not file:

        await execute(
            """
            UPDATE file_purchases
            SET status='pending'
            WHERE id=$1
              AND status='verifying'
            """,
            purchase_id,
        )

        return await call.answer(
            "❌ File tidak ditemukan.",
            show_alert=True,
        )

    await call.answer(
        "⏳ Memproses pembayaran..."
    )

    user_id = safe_int(
        purchase.get("user_id")
    )

    try:

        user_message = await call.bot.send_message(
            user_id,
            "⏳ Pembayaran manual disetujui. Memproses file...",
        )

    except Exception:

        await execute(
            """
            UPDATE file_purchases
            SET status='pending'
            WHERE id=$1
              AND status='verifying'
            """,
            purchase_id,
        )

        return await call.answer(
            "❌ User tidak dapat dihubungi.",
            show_alert=True,
        )

    # --------------------------------------------------------
    # VERIFYING -> PAID
    # --------------------------------------------------------

    success = await finish_manual_payment(
        call.bot,
        purchase,
        file,
        purchase.get("payment_id"),
        user_message,
    )

    if not success:

        return await call.answer(
            "❌ Pembayaran gagal diproses.",
            show_alert=True,
        )

    try:

        await call.message.edit_text(
            (
                "✅ <b>PEMBAYARAN DISETUJUI</b>\n\n"
                f"🧾 ID: <code>{purchase_id}</code>\n"
                f"👤 User: <code>{user_id}</code>\n"
                f"📦 File: "
                f"<b>{clean_html(file.get('title'))}</b>\n"
                f"🔑 Code: "
                f"<code>{clean_html(file.get('code'))}</code>\n"
                f"💰 Harga: "
                f"<b>{format_rupiah(purchase.get('paid_price'))}</b>\n\n"
                "📦 Media sudah diproses."
            ),
            parse_mode="HTML",
            reply_markup=None,
        )

    except Exception:

        logger.warning(
            "EDIT APPROVE MESSAGE FAILED",
            exc_info=True,
        )


# ============================================================
# FINISH MANUAL
# ============================================================

async def finish_manual_payment(
    bot,
    purchase,
    file,
    invoice,
    message,
):

    purchase_id = safe_int(
        purchase.get("id")
    )

    if purchase_id <= 0:
        return False

    try:

        media_list = parse_media(
            file.get("media")
        )

        if not media_list:

            # Kembalikan ke pending supaya admin
            # tidak kehilangan transaksi.
            await execute(
                """
                UPDATE file_purchases
                SET status='pending'
                WHERE id=$1
                  AND status='verifying'
                """,
                purchase_id,
            )

            await message.answer(
                "❌ Media file kosong."
            )

            return False

        # ----------------------------------------------------
        # VERIFYING -> PAID
        # ----------------------------------------------------

        updated = await fetchrow(
            """
            UPDATE file_purchases
            SET
                status='paid',
                paid_at=COALESCE(
                    paid_at,
                    NOW()
                )
            WHERE id=$1
              AND status='verifying'
            RETURNING *
            """,
            purchase_id,
        )

        if not updated:

            logger.warning(
                "MANUAL PAYMENT CLAIM LOST | purchase=%s",
                purchase_id,
            )

            return False

        purchase = updated

        # ----------------------------------------------------
        # MEDIA SESSION
        # ----------------------------------------------------

        media_id = secrets.token_hex(16)

        session_data = {
            "user_id": int(
                purchase["user_id"]
            ),
            "media": media_list,
            "share_media": bool(
                file.get("share_media", False)
            ),
            "invoice": invoice,
            "purchase_id": purchase_id,
        }

        await safe_set(
            f"paidmedia:{media_id}",
            session_data,
            ex=MEDIA_TTL,
        )

        await execute(
            """
            UPDATE file_purchases
            SET media_session_id=$1
            WHERE id=$2
            """,
            media_id,
            purchase_id,
        )

        # ----------------------------------------------------
        # COUNT
        # ----------------------------------------------------

        try:

            await execute(
                """
                UPDATE files
                SET
                    buy_count=COALESCE(
                        buy_count,
                        0
                    ) + 1,

                    sold=COALESCE(
                        sold,
                        0
                    ) + 1

                WHERE code=$1
                """,
                file["code"],
            )

        except Exception:

            logger.exception(
                "MANUAL BUY COUNT ERROR"
            )

        # ----------------------------------------------------
        # FREE CODE
        # ----------------------------------------------------

        try:

            completed_rows = await fetch(
                """
                UPDATE free_code_progress
                SET
                    purchase_count=LEAST(
                        3,
                        COALESCE(
                            purchase_count,
                            0
                        ) + 1
                    ),

                    completed=(
                        LEAST(
                            3,
                            COALESCE(
                                purchase_count,
                                0
                            ) + 1
                        ) >= 3
                    ),

                    completed_at=CASE
                        WHEN LEAST(
                            3,
                            COALESCE(
                                purchase_count,
                                0
                            ) + 1
                        ) >= 3
                        THEN COALESCE(
                            completed_at,
                            NOW()
                        )
                        ELSE completed_at
                    END

                WHERE code=$1
                  AND user_id=$2
                  AND completed=FALSE

                RETURNING
                    user_id,
                    purchase_count,
                    completed
                """,
                file["code"],
                purchase["user_id"],
            )

            for row in completed_rows:

                if row["completed"]:

                    try:

                        await bot.send_message(
                            row["user_id"],
                            (
                                "🎉 <b>Progress Code Free 3/3!</b>\n\n"
                                f"Code "
                                f"<code>{clean_html(file['code'])}</code>\n"
                                "sudah mencapai 3 pembelian berhasil.\n\n"
                                "🔓 Code sekarang bisa dibuka gratis."
                            ),
                            parse_mode="HTML",
                        )

                    except Exception:

                        logger.exception(
                            "FREE PROGRESS NOTIFY ERROR"
                        )

        except Exception:

            logger.exception(
                "MANUAL FREE CODE ERROR"
            )

        # ----------------------------------------------------
        # SELLER PROFIT
        # ----------------------------------------------------

        try:

            price = safe_int(
                file.get("price")
            )

            income = int(
                price * 0.5
            )

            owner_id = file.get(
                "owner_id"
            )

            if owner_id and income > 0:

                await execute(
                    """
                    UPDATE users
                    SET
                        balance=COALESCE(
                            balance,
                            0
                        ) + $1,

                        total_earn=COALESCE(
                            total_earn,
                            0
                        ) + $1

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
                    ($1,$2,$3,$4)
                    """,
                    owner_id,
                    "file_sale",
                    income,
                    f"Pendapatan file {file['code']}",
                )

        except Exception:

            logger.exception(
                "MANUAL SELLER PROFIT ERROR"
            )

        # ----------------------------------------------------
        # NOTIFICATION
        # ----------------------------------------------------

        try:

            if NOTIF_CHANNEL_ID:

                masked = mask_user_id(
                    purchase["user_id"]
                )

                buy_url = (
                    "https://t.me/mktplbot"
                    f"?start={file['code']}"
                )

                keyboard = InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            InlineKeyboardButton(
                                text="🛒 Buy Now",
                                url=buy_url,
                            )
                        ]
                    ]
                )

                await bot.send_message(
                    NOTIF_CHANNEL_ID,
                    (
                        "💸 <b>FILE PAYMENT SUCCESS</b>\n\n"
                        f"📄 Judul: "
                        f"<b>{clean_html(file.get('title'))}</b>\n"
                        f"📁 Code: "
                        f"<code>{clean_html(file.get('code'))}</code>\n"
                        f"👤 User: "
                        f"<code>{masked}</code>\n"
                        f"💰 Harga: "
                        f"<b>{format_rupiah(purchase.get('paid_price'))}</b>\n"
                        "💳 Payment: <b>MANUAL</b>"
                    ),
                    parse_mode="HTML",
                    reply_markup=keyboard,
                )

        except Exception:

            logger.exception(
                "MANUAL PAYMENT NOTIFICATION ERROR"
            )

        # ----------------------------------------------------
        # DELETE QR
        # ----------------------------------------------------

        try:

            qr_message_id = purchase.get(
                "qr_message_id"
            )

            qr_chat_id = purchase.get(
                "qr_chat_id"
            )

            if qr_message_id and qr_chat_id:

                await bot.delete_message(
                    chat_id=int(qr_chat_id),
                    message_id=int(qr_message_id),
                )

        except Exception:

            logger.warning(
                "DELETE MANUAL QR FAILED",
                exc_info=True,
            )

        # ----------------------------------------------------
        # MEDIA MENU
        # ----------------------------------------------------

        total = len(
            media_list
        )

        await message.answer(
            (
                "🎉 <b>Pembayaran berhasil!</b>\n\n"
                f"📦 Total File: <b>{total}</b>\n\n"
                "Silakan pilih pengiriman:"
            ),
            parse_mode="HTML",
            reply_markup=media_keyboard(
                media_id,
                1,
                total,
            ),
        )

        logger.info(
            "MANUAL PAYMENT FINISHED | purchase=%s | user=%s | code=%s",
            purchase_id,
            purchase["user_id"],
            file["code"],
        )

        return True

    except Exception:

        logger.exception(
            "FINISH MANUAL PAYMENT ERROR"
        )

        return False


# ============================================================
# REJECT
# ============================================================

@router.callback_query(
    F.data.startswith("reject:")
)
async def reject_manual(
    call: CallbackQuery,
    state: FSMContext,
):

    if not is_admin(
        call.from_user.id
    ):

        return await call.answer(
            "❌ Kamu bukan admin.",
            show_alert=True,
        )

    try:

        purchase_id = int(
            call.data.split(
                ":",
                1,
            )[1]
        )

    except (ValueError, IndexError):

        return await call.answer(
            "❌ ID transaksi tidak valid.",
            show_alert=True,
        )

    purchase = await fetchrow(
        """
        SELECT *
        FROM file_purchases
        WHERE id=$1
          AND status='pending'
          AND payment_id LIKE 'MANUAL-%'
        LIMIT 1
        """,
        purchase_id,
    )

    if not purchase:

        return await call.answer(
            "❌ Transaksi tidak ditemukan atau sudah diproses.",
            show_alert=True,
        )

    await state.set_state(
        RejectPaymentState.waiting_reason
    )

    await state.update_data(
        purchase_id=purchase_id,
        admin_id=int(
            call.from_user.id
        ),
        admin_chat_id=int(
            call.message.chat.id
        ),
        admin_message_id=int(
            call.message.message_id
        ),
    )

    await call.message.reply(
        (
            "❌ <b>REJECT PEMBAYARAN</b>\n\n"
            f"🧾 ID: <code>{purchase_id}</code>\n"
            f"👤 User: <code>{purchase['user_id']}</code>\n"
            f"📦 Code: <code>{clean_html(purchase['file_code'])}</code>\n\n"
            "📝 Kirim alasan penolakan.\n\n"
            "Ketik <code>/cancelreject</code> untuk membatalkan."
        ),
        parse_mode="HTML",
    )

    await call.answer()


# ============================================================
# CANCEL REJECT
# ============================================================

@router.message(
    RejectPaymentState.waiting_reason,
    F.text == "/cancelreject",
)
async def cancel_reject_reason(
    message: Message,
    state: FSMContext,
):

    if not is_admin(
        message.from_user.id
    ):
        return

    data = await state.get_data()

    purchase_id = data.get(
        "purchase_id"
    )

    await state.clear()

    await message.answer(
        (
            "↩️ <b>Reject dibatalkan.</b>\n\n"
            f"Transaksi <code>{purchase_id}</code> "
            "tetap pending."
        ),
        parse_mode="HTML",
    )


# ============================================================
# RECEIVE REJECT
# ============================================================

@router.message(
    RejectPaymentState.waiting_reason,
    F.text,
)
async def receive_reject_reason(
    message: Message,
    state: FSMContext,
):

    if not is_admin(
        message.from_user.id
    ):

        return await message.answer(
            "❌ Kamu bukan admin."
        )

    data = await state.get_data()

    purchase_id = data.get(
        "purchase_id"
    )

    admin_id = data.get(
        "admin_id"
    )

    if (
        admin_id
        and int(message.from_user.id)
        != int(admin_id)
    ):

        return await message.answer(
            "❌ Permintaan ini milik admin lain."
        )

    if not purchase_id:

        await state.clear()

        return await message.answer(
            "❌ Data transaksi tidak ditemukan."
        )

    reason = str(
        message.text or ""
    ).strip()

    if not reason:

        return await message.answer(
            "❌ Alasan tidak boleh kosong."
        )

    if len(reason) > 1000:

        return await message.answer(
            "❌ Maksimal 1000 karakter."
        )

    # --------------------------------------------------------
    # ATOMIC REJECT
    # --------------------------------------------------------

    rejected = await fetchrow(
        """
        UPDATE file_purchases
        SET status='rejected'
        WHERE id=$1
          AND status='pending'
          AND payment_id LIKE 'MANUAL-%'
        RETURNING *
        """,
        purchase_id,
    )

    if not rejected:

        await state.clear()

        return await message.answer(
            "❌ Transaksi sudah diproses admin lain."
        )

    user_id = safe_int(
        rejected.get("user_id")
    )

    code = str(
        rejected.get("file_code") or ""
    )

    safe_reason = clean_html(
        reason
    )

    # --------------------------------------------------------
    # USER
    # --------------------------------------------------------

    user_notified = False

    try:

        await message.bot.send_message(
            user_id,
            (
                "❌ <b>Pembayaran Ditolak</b>\n\n"
                f"📦 Code: <code>{clean_html(code)}</code>\n\n"
                "📝 <b>Alasan Admin:</b>\n"
                f"{safe_reason}\n\n"
                "💡 Silakan lakukan pembayaran ulang."
            ),
            parse_mode="HTML",
        )

        user_notified = True

    except Exception:

        logger.exception(
            "REJECT USER NOTIFICATION ERROR"
        )

    # --------------------------------------------------------
    # DELETE QR
    # --------------------------------------------------------

    qr_deleted = False

    try:

        qr_message_id = rejected.get(
            "qr_message_id"
        )

        qr_chat_id = rejected.get(
            "qr_chat_id"
        )

        if qr_message_id and qr_chat_id:

            await message.bot.delete_message(
                chat_id=int(qr_chat_id),
                message_id=int(qr_message_id),
            )

            qr_deleted = True

    except Exception:

        logger.warning(
            "DELETE REJECT QR FAILED",
            exc_info=True,
        )

    # --------------------------------------------------------
    # ADMIN MESSAGE
    # --------------------------------------------------------

    if (
        data.get("admin_chat_id")
        and data.get("admin_message_id")
    ):

        try:

            await message.bot.edit_message_text(
                chat_id=int(
                    data["admin_chat_id"]
                ),
                message_id=int(
                    data["admin_message_id"]
                ),
                text=(
                    "❌ <b>PEMBAYARAN DITOLAK</b>\n\n"
                    f"🧾 ID: <code>{purchase_id}</code>\n"
                    f"👤 User: <code>{user_id}</code>\n"
                    f"📦 Code: <code>{clean_html(code)}</code>\n\n"
                    "📝 <b>Alasan:</b>\n"
                    f"{safe_reason}"
                ),
                parse_mode="HTML",
                reply_markup=None,
            )

        except Exception:

            logger.warning(
                "EDIT REJECT ADMIN MESSAGE ERROR",
                exc_info=True,
            )

    await message.answer(
        (
            "❌ <b>PEMBAYARAN DITOLAK</b>\n\n"
            f"🧾 ID: <code>{purchase_id}</code>\n"
            f"👤 User: <code>{user_id}</code>\n"
            f"📦 Code: <code>{clean_html(code)}</code>\n\n"
            f"📝 Alasan:\n{safe_reason}\n\n"
            f"👤 Notifikasi user: "
            f"{'✅' if user_notified else '❌'}\n"
            f"🗑 QR dihapus: "
            f"{'✅' if qr_deleted else '⚠️'}"
        ),
        parse_mode="HTML",
    )

    await state.clear()


# ============================================================
# CLOSE
# ============================================================

@router.callback_query(
    F.data == "close"
)
async def close_payment(
    call: CallbackQuery,
    state: FSMContext,
):

    await state.clear()

    try:
        await call.message.delete()
    except Exception:
        pass

    await call.answer(
        "Pembayaran dibatalkan."
    )


# ============================================================
# MEDIA SECURITY
# ============================================================

async def get_owned_media_session(
    call: CallbackQuery,
    media_id: str,
):

    if not media_id:

        await call.answer(
            "❌ Session tidak valid.",
            show_alert=True,
        )

        return None

    data = await safe_get(
        f"paidmedia:{media_id}"
    )

    if not data:

        await call.answer(
            "❌ Session media sudah expired.",
            show_alert=True,
        )

        return None

    if not isinstance(data, dict):

        await call.answer(
            "❌ Data session tidak valid.",
            show_alert=True,
        )

        return None

    session_user_id = data.get(
        "user_id"
    )

    try:

        if int(session_user_id) != int(
            call.from_user.id
        ):

            raise ValueError

    except Exception:

        await call.answer(
            "❌ Akses media tidak diizinkan.",
            show_alert=True,
        )

        return None

    return data


# ============================================================
# MEDIA KEYBOARD
# ============================================================

def media_keyboard(
    media_id: str,
    page: int,
    total: int,
):

    max_page = max(
        1,
        (total + PER_PAGE - 1) // PER_PAGE,
    )

    page = max(
        1,
        min(page, max_page),
    )

    buttons = []
    nav = []

    if page > 1:

        nav.append(
            InlineKeyboardButton(
                text="⬅️",
                callback_data=f"mp:{media_id}:{page - 1}",
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
                callback_data=f"mp:{media_id}:{page + 1}",
            )
        )

    buttons.append(nav)

    buttons.append(
        [
            InlineKeyboardButton(
                text="📤 Kirim Halaman",
                callback_data=f"sp:{media_id}:{page}",
            )
        ]
    )

    buttons.append(
        [
            InlineKeyboardButton(
                text="📦 Kirim Semua",
                callback_data=f"sa:{media_id}",
            )
        ]
    )

    return InlineKeyboardMarkup(
        inline_keyboard=buttons
    )


# ============================================================
# SEND PAGE
# ============================================================

@router.callback_query(
    F.data.startswith("sp:")
)
async def send_page_media(
    call: CallbackQuery,
):

    try:

        parts = call.data.split(":")

        if len(parts) != 3:
            raise ValueError

        _, media_id, page_raw = parts

        page = int(page_raw)

    except Exception:

        return await call.answer(
            "❌ Data halaman tidak valid.",
            show_alert=True,
        )

    data = await get_owned_media_session(
        call,
        media_id,
    )

    if not data:
        return

    media_list = data.get(
        "media",
        [],
    )

    if not isinstance(
        media_list,
        list,
    ):

        return await call.answer(
            "❌ Data media tidak valid.",
            show_alert=True,
        )

    total = len(
        media_list
    )

    max_page = max(
        1,
        (total + PER_PAGE - 1) // PER_PAGE,
    )

    if page < 1 or page > max_page:

        return await call.answer(
            "❌ Halaman tidak valid.",
            show_alert=True,
        )

    start = (
        page - 1
    ) * PER_PAGE

    items = media_list[
        start:start + PER_PAGE
    ]

    if not items:

        return await call.answer(
            "❌ Halaman kosong.",
            show_alert=True,
        )

    await call.answer(
        "📤 Mengirim file..."
    )

    sent = 0

    for item in items:

        try:

            message_id = item.get(
                "message_id"
            )

            if not message_id:
                continue

            await call.bot.copy_message(
                chat_id=call.from_user.id,
                from_chat_id=STORAGE_CHANNEL_ID,
                message_id=int(message_id),
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
# SEND ALL
# ============================================================

@router.callback_query(
    F.data.startswith("sa:")
)
async def send_all_media(
    call: CallbackQuery,
):

    try:

        parts = call.data.split(":")

        if len(parts) != 2:
            raise ValueError

        _, media_id = parts

    except Exception:

        return await call.answer(
            "❌ Session tidak valid.",
            show_alert=True,
        )

    data = await get_owned_media_session(
        call,
        media_id,
    )

    if not data:
        return

    media_list = data.get(
        "media",
        [],
    )

    if not media_list:

        return await call.answer(
            "❌ Media kosong.",
            show_alert=True,
        )

    await call.answer(
        "📦 Mengirim semua file..."
    )

    total = len(
        media_list
    )

    progress = await call.message.answer(
        f"⏳ Mengirim 0/{total}"
    )

    sent = 0

    for index, item in enumerate(
        media_list,
        start=1,
    ):

        try:

            message_id = item.get(
                "message_id"
            )

            if not message_id:
                continue

            await call.bot.copy_message(
                chat_id=call.from_user.id,
                from_chat_id=STORAGE_CHANNEL_ID,
                message_id=int(message_id),
            )

            sent += 1

            if (
                index % 5 == 0
                or index == total
            ):

                try:

                    await progress.edit_text(
                        f"⏳ Mengirim {index}/{total}"
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
                f"📦 Berhasil: {sent}/{total}"
            )
        )

    except Exception:
        pass


# ============================================================
# MEDIA NAVIGATION
# ============================================================

@router.callback_query(
    F.data.startswith("mp:")
)
async def media_page(
    call: CallbackQuery,
):

    try:

        parts = call.data.split(":")

        if len(parts) != 3:
            raise ValueError

        _, media_id, page_raw = parts

        page = int(page_raw)

    except Exception:

        return await call.answer(
            "❌ Data halaman tidak valid.",
            show_alert=True,
        )

    data = await get_owned_media_session(
        call,
        media_id,
    )

    if not data:
        return

    media_list = data.get(
        "media",
        [],
    )

    if not media_list:

        return await call.answer(
            "❌ Media tidak ditemukan.",
            show_alert=True,
        )

    total = len(
        media_list
    )

    max_page = max(
        1,
        (total + PER_PAGE - 1) // PER_PAGE,
    )

    if page < 1 or page > max_page:

        return await call.answer(
            "❌ Halaman tidak valid.",
            show_alert=True,
        )

    try:

        await call.message.edit_reply_markup(
            reply_markup=media_keyboard(
                media_id,
                page,
                total,
            )
        )

    except Exception:

        logger.warning(
            "MEDIA PAGINATION ERROR",
            exc_info=True,
        )

    await call.answer()


# ============================================================
# NONE
# ============================================================

@router.callback_query(
    F.data == "none"
)
async def none_callback(
    call: CallbackQuery,
):

    await call.answer()
