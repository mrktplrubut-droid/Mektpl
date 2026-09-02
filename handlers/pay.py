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


async def get_pending_purchase(
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
# CASHI API
# ============================================================

def cashi_headers() -> dict:

    return {
        "x-api-key": str(CASHI_API_KEY or "").strip(),
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

                if response.status < 200 or response.status >= 300:

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

                if response.status < 200 or response.status >= 300:

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
# MANUAL FALLBACK KEYBOARD
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
# PAYMENT ENTRY → CASHI
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

    file = await get_file_by_code(
        code
    )

    if not file:

        return await call.answer(
            "❌ File tidak ditemukan.",
            show_alert=True,
        )

    price = safe_int(
        file.get("price")
    )

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
# DIRECT CASHI PAYMENT
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

    file = await get_file_by_code(
        code
    )

    if not file:

        return await call.answer(
            "❌ File tidak ditemukan.",
            show_alert=True,
        )

    price = safe_int(
        file.get("price")
    )

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

    code = str(
        code
    ).strip()

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
    # EXISTING PENDING
    # --------------------------------------------------------

    existing = await get_pending_purchase(
        user_id,
        code,
    )

    if existing:

        payment_id = str(
            existing.get("payment_id") or ""
        ).strip()

        qr_url = str(
            existing.get("qr_image") or ""
        ).strip()

        payment_url = str(
            existing.get("payment_url") or ""
        ).strip()

        # Jika transaksi Cashi lama masih ada,
        # cek status dahulu.
        if payment_id.startswith("CASHI-"):

            status_data = await cashi_check_status(
                payment_id
            )

            if status_data:

                status = normalize_status(
                    status_data.get("status")
                )

                if status in SUCCESS_STATUSES:

                    return await process_cashi_success(
                        call.bot,
                        existing,
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
                        existing["id"],
                    )

                    existing = None

        if existing:

            keyboard = await payment_check_keyboard(
                code,
                payment_id,
            )

            # ------------------------------------------------
            # QR URL CASHI
            # ------------------------------------------------

            if qr_url:

                try:

                    await call.message.answer_photo(
                        photo=qr_url,
                        caption=(
                            "💳 <b>PEMBAYARAN CASHI</b>\n\n"
                            f"📄 File:\n"
                            f"<b>{clean_html(file.get('title'))}</b>\n\n"
                            f"🔑 Code:\n"
                            f"<code>{clean_html(code)}</code>\n\n"
                            f"💰 Harga:\n"
                            f"<b>{format_rupiah(price)}</b>\n\n"
                            "📌 Scan QR Cashi di atas.\n"
                            "Setelah pembayaran berhasil, "
                            "tekan tombol <b>🔄 Cek Pembayaran</b>."
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
                        "🔗 Silakan buka halaman pembayaran Cashi.\n\n"
                        "Setelah selesai, tekan "
                        "<b>🔄 Cek Pembayaran</b>."
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
                                InlineKeyboardButton(
                                    text="🔄 Cek Pembayaran",
                                    callback_data=keyboard.inline_keyboard[0][0].callback_data,
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

            return await call.answer(
                "⏳ Transaksi masih aktif.",
                show_alert=True,
            )

    # --------------------------------------------------------
    # CREATE NEW PURCHASE
    # --------------------------------------------------------

    payment_id = (
        f"CASHI-{user_id}-"
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
            RETURNING *
            """,
            user_id,
            code,
            file.get("owner_id"),
            price,
            payment_id,
        )

    except Exception:

        logger.exception(
            "CREATE CASHI PURCHASE ERROR"
        )

        return await call.answer(
            "❌ Gagal membuat transaksi.",
            show_alert=True,
        )

    if not purchase:

        return await call.answer(
            "❌ Transaksi gagal dibuat.",
            show_alert=True,
        )

    await call.answer(
        "⏳ Membuat pembayaran Cashi..."
    )

    # --------------------------------------------------------
    # CASHI CREATE ORDER
    # --------------------------------------------------------

    cashi = await cashi_create_order(
        amount=price,
        order_id=payment_id,
    )

    if not cashi:

        # Jangan hapus transaksi.
        # Tandai gagal sehingga user bisa mencoba lagi.
        await execute(
            """
            UPDATE file_purchases
            SET status='failed'
            WHERE id=$1
              AND status='pending'
            """,
            purchase["id"],
        )

        # ----------------------------------------------------
        # FALLBACK MANUAL QR
        # ----------------------------------------------------

        if MANUAL_QR_FILE_ID:

            return await create_manual_fallback(
                call,
                code,
                file,
            )

        return await call.message.answer(
            (
                "❌ <b>Pembayaran Cashi gagal dibuat.</b>\n\n"
                "Silakan coba lagi beberapa saat."
            ),
            parse_mode="HTML",
        )

    # --------------------------------------------------------
    # CASHI DATA
    # --------------------------------------------------------

    cashi_order_id = str(
        cashi.get("orderId")
        or cashi.get("order_id")
        or payment_id
    )

    qr_url = str(
        cashi.get("qrUrl")
        or ""
    ).strip()

    checkout_url = str(
        cashi.get("checkout_url")
        or ""
    ).strip()

    # Cashi responses are JSON and may contain expires_at as a string.
    # Normalize it before passing it to asyncpg (timestamptz).
    expires_at = Cashi._parse_datetime(
        cashi.get("expires_at")
    )

    # --------------------------------------------------------
    # SAVE CASHI DATA
    # --------------------------------------------------------

    await execute(
        """
        UPDATE file_purchases
        SET
            payment_id=$1,
            qr_image=$2,
            payment_url=$3,
            expires_at=$4
        WHERE id=$5
          AND status='pending'
        """,
        cashi_order_id,
        qr_url or None,
        checkout_url or None,
        expires_at,
        purchase["id"],
    )

    # Refresh
    purchase = await fetchrow(
        """
        SELECT *
        FROM file_purchases
        WHERE id=$1
        LIMIT 1
        """,
        purchase["id"],
    )

    keyboard = await payment_check_keyboard(
        code,
        cashi_order_id,
    )

    # --------------------------------------------------------
    # SEND QR
    # --------------------------------------------------------

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
        "⚡ Pembayaran akan diverifikasi otomatis oleh Cashi.\n"
        "⚠️ Jangan melakukan pembayaran dua kali."
    )

    try:

        if qr_url:

            msg = await call.message.answer_photo(
                photo=qr_url,
                caption=caption,
                parse_mode="HTML",
                reply_markup=keyboard,
            )

        elif checkout_url:

            msg = await call.message.answer(
                (
                    f"{caption}\n\n"
                    "👇 Klik tombol <b>Bayar Sekarang</b>."
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
                                callback_data=(
                                    keyboard
                                    .inline_keyboard[0][0]
                                    .callback_data
                                ),
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

            await call.message.answer(
                caption,
                parse_mode="HTML",
                reply_markup=keyboard,
            )

            msg = None

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
                purchase["id"],
            )

    except Exception:

        logger.exception(
            "SEND CASHI PAYMENT ERROR"
        )

        return await call.message.answer(
            (
                "❌ Pembayaran berhasil dibuat di Cashi, "
                "tetapi QR gagal dikirim.\n\n"
                "Silakan buka pembayaran kembali."
            ),
            parse_mode="HTML",
        )


# ============================================================
# MANUAL FALLBACK
# ============================================================

async def create_manual_fallback(
    call: CallbackQuery,
    code: str,
    file,
):

    if not MANUAL_QR_FILE_ID:

        return await call.message.answer(
            "❌ Cashi sedang tidak tersedia.",
        )

    user_id = int(
        call.from_user.id
    )

    price = safe_int(
        file.get("price")
    )

    payment_id = (
        f"MANUAL-{user_id}-"
        f"{secrets.token_hex(8)}"
    )

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
        RETURNING *
        """,
        user_id,
        code,
        file.get("owner_id"),
        price,
        payment_id,
    )

    keyboard = await manual_payment_keyboard(
        code
    )

    msg = await call.message.answer_photo(
        photo=MANUAL_QR_FILE_ID,
        caption=(
            "📷 <b>PEMBAYARAN MANUAL</b>\n\n"
            f"📄 <b>{clean_html(file.get('title'))}</b>\n\n"
            f"🔑 Code:\n"
            f"<code>{clean_html(code)}</code>\n\n"
            f"💰 Harga:\n"
            f"<b>{format_rupiah(price)}</b>\n\n"
            "⚠️ Cashi sedang tidak dapat membuat transaksi.\n"
            "Gunakan QR manual di atas.\n\n"
            "Setelah membayar, tekan "
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
        """,
        msg.message_id,
        msg.chat.id,
        purchase["id"],
    )


# ============================================================
# CASHI CHECK PAYMENT
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

    # --------------------------------------------------------
    # LOCK
    # --------------------------------------------------------

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
    # PURCHASE
    # --------------------------------------------------------

    purchase = await fetchrow(
        """
        SELECT *
        FROM file_purchases
        WHERE user_id=$1
          AND file_code=$2
          AND payment_id=$3
        ORDER BY id DESC
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
                "Silakan coba tekan "
                "<b>🔄 Cek Pembayaran</b> "
                "beberapa saat lagi."
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

        success = await process_cashi_success(
            call.bot,
            purchase,
            file,
        )

        if success:

            return

        return await call.message.answer(
            "⚠️ Pembayaran terdeteksi berhasil, tetapi proses file gagal. Admin akan mengecek transaksi ini."
        )

    # --------------------------------------------------------
    # FAILED
    # --------------------------------------------------------

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

        return await call.message.answer(
            (
                "❌ <b>Pembayaran tidak berhasil.</b>\n\n"
                f"Status Cashi: "
                f"<code>{clean_html(status.upper())}</code>\n\n"
                "Silakan buat pembayaran baru."
            ),
            parse_mode="HTML",
        )

    # --------------------------------------------------------
    # STILL PENDING
    # --------------------------------------------------------

    return await call.message.answer(
        (
            "⏳ <b>Pembayaran belum terkonfirmasi.</b>\n\n"
            "Cashi belum memberikan status pembayaran berhasil.\n\n"
            "Jika kamu sudah membayar, tunggu beberapa detik "
            "lalu tekan <b>🔄 Cek Pembayaran</b> lagi."
        ),
        parse_mode="HTML",
    )


# ============================================================
# PROCESS CASHI SUCCESS
# ============================================================

async def process_cashi_success(
    bot,
    purchase,
    file,
):

    user_id = safe_int(
        purchase.get("user_id")
    )

    if user_id <= 0:
        return False

    try:

        user_message = await bot.send_message(
            user_id,
            "⏳ Pembayaran Cashi berhasil terdeteksi. Memproses file...",
        )

    except Exception:

        logger.exception(
            "CASHI USER MESSAGE ERROR"
        )

        return False

    return await finish_payment(
        bot,
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

        # ----------------------------------------------------
        # ATOMIC PAID
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
        # BUY COUNT
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
                "BUY COUNT UPDATE ERROR"
            )

        # ----------------------------------------------------
        # FREE CODE PROGRESS
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
                "FREE CODE PROGRESS UPDATE ERROR"
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
                "SELLER PROFIT ERROR"
            )

        # ----------------------------------------------------
        # CHANNEL NOTIFICATION
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
                        "💳 Payment: <b>CASHI</b>"
                    ),
                    parse_mode="HTML",
                    reply_markup=keyboard,
                )

        except Exception:

            logger.exception(
                "PAYMENT NOTIFICATION ERROR"
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
                "DELETE PAYMENT QR FAILED",
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

    purchase = await get_pending_purchase(
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
        f"<code>{clean_html(purchase.get('payment_id'))}</code>"
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
            "✅ Permintaan pembayaran sudah dikirim "
            "ke admin.\n\n"
            "⏳ Tunggu verifikasi admin."
        )
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

    purchase = await fetchrow(
        """
        SELECT *
        FROM file_purchases
        WHERE id=$1
          AND status='pending'
        LIMIT 1
        """,
        purchase_id,
    )

    if not purchase:

        return await call.answer(
            "❌ Transaksi sudah diproses.",
            show_alert=True,
        )

    file = await get_file_by_code(
        purchase["file_code"]
    )

    if not file:

        return await call.answer(
            "❌ File tidak ditemukan.",
            show_alert=True,
        )

    await call.answer(
        "⏳ Memproses..."
    )

    user_id = safe_int(
        purchase.get("user_id")
    )

    try:

        user_message = await call.bot.send_message(
            user_id,
            "⏳ Pembayaran sedang diproses...",
        )

    except Exception:

        return await call.answer(
            "❌ User tidak dapat dihubungi.",
            show_alert=True,
        )

    success = await finish_payment(
        call.bot,
        purchase,
        file,
        purchase.get("payment_id"),
        user_message,
    )

    if not success:

        return await call.answer(
            "❌ Pembayaran sudah diproses / gagal.",
            show_alert=True,
        )

    try:

        await call.message.edit_text(
            (
                "✅ <b>PEMBAYARAN DISETUJUI</b>\n\n"
                f"👤 User: <code>{user_id}</code>\n"
                f"📦 File: "
                f"<b>{clean_html(file.get('title'))}</b>\n"
                f"🔑 Code: "
                f"<code>{clean_html(file.get('code'))}</code>\n"
                f"💰 Harga: "
                f"<b>{format_rupiah(purchase.get('paid_price'))}</b>\n\n"
                "📦 Media sudah dikirim."
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
        LIMIT 1
        """,
        purchase_id,
    )

    if not purchase:

        return await call.answer(
            "❌ Transaksi tidak ditemukan.",
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
