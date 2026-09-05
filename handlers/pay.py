import asyncio
import base64
import html
import json
import logging
import os
import secrets
from datetime import datetime, timezone
from typing import Any
import aiohttp
from aiogram import Router, F
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    Message,
)
from database import fetchrow, fetch, execute
from utils.media_sender import safe_copy_from_storage
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
CASHI_BASE_URL = os.getenv(
    "CASHI_BASE_URL",
    "https://cashi.id",
).strip().rstrip("/")
CASHI_CREATE_URL = (
    f"{CASHI_BASE_URL}/api/create-order"
)
PAYMENT_MODE = os.getenv(
    "PAYMENT_MODE",
    "both",
).strip().lower()
if PAYMENT_MODE not in {
    "both",
    "cashi",
    "manual",
}:
    PAYMENT_MODE = "both"
CASHI_ENABLED = bool(
    str(CASHI_API_KEY or "").strip()
)
AUTO_PAYMENT_ENABLED = (
    PAYMENT_MODE in {
        "both",
        "cashi",
    }
    and CASHI_ENABLED
)
MANUAL_QR_FILE_ID = str(
    MANUAL_QR_FILE_ID or ""
).strip()
MANUAL_PAYMENT_ENABLED = (
    PAYMENT_MODE in {
        "both",
        "manual",
    }
    and bool(MANUAL_QR_FILE_ID)
)
SUCCESS_STATUSES = {
    "paid",
    "success",
    "settled",
    "completed",
    "completed_payment",
    "success_payment",
}
FAILED_STATUSES = {
    "expired",
    "cancel",
    "cancelled",
    "canceled",
    "failed",
    "rejected",
    "void",
}
REUSABLE_PURCHASE_STATUSES = {
    "failed",
    "rejected",
    "expired",
    "cancel",
    "cancelled",
    "canceled",
}
ACTIVE_PURCHASE_STATUSES = {
    "pending",
    "verifying",
}
# ============================================================
# STARTUP LOG
# ============================================================
logger.info(
    "PAYMENT_MODE : %s",
    PAYMENT_MODE,
)
logger.info(
    "MANUAL_PAYMENT : %s",
    "ON" if MANUAL_PAYMENT_ENABLED else "OFF",
)
logger.info(
    "CASHI_ENABLED : %s",
    "ON" if CASHI_ENABLED else "OFF",
)
logger.info(
    "AUTO_PAYMENT : %s",
    "ON" if AUTO_PAYMENT_ENABLED else "OFF",
)
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
def safe_int(
    value: Any,
    default: int = 0,
) -> int:
    try:
        return int(value)
    except (
        ValueError,
        TypeError,
    ):
        return default
def get_admin_ids() -> set[int]:
    try:
        raw = ADMIN_IDS
        if raw is None:
            return set()
        if isinstance(raw, str):
            values = raw.replace(
                ";",
                ",",
            ).split(",")
        elif isinstance(
            raw,
            (list, tuple, set),
        ):
            values = raw
        else:
            values = [raw]
        result = set()
        for value in values:
            try:
                value = str(
                    value
                ).strip()
                if value:
                    result.add(
                        int(value)
                    )
            except (
                ValueError,
                TypeError,
            ):
                continue
        return result
    except Exception:
        logger.exception(
            "GET ADMIN IDS ERROR"
        )
        return set()
def is_admin(
    user_id: int,
) -> bool:
    try:
        return int(
            user_id
        ) in get_admin_ids()
    except Exception:
        return False
# ============================================================
# GENERIC CASHI RESPONSE HELPERS
# ============================================================
def recursive_find(
    data: Any,
    keys: set[str],
):
    if isinstance(data, dict):
        for key in keys:
            if (
                key in data
                and data[key]
                not in (
                    None,
                    "",
                )
            ):
                return data[key]
        for value in data.values():
            found = recursive_find(
                value,
                keys,
            )
            if found not in (
                None,
                "",
            ):
                return found
    elif isinstance(data, list):
        for item in data:
            found = recursive_find(
                item,
                keys,
            )
            if found not in (
                None,
                "",
            ):
                return found
    return None
def extract_cashi_status(
    data: Any,
) -> str:
    value = recursive_find(
        data,
        {
            "status",
            "payment_status",
            "paymentStatus",
            "state",
        },
    )
    return normalize_status(
        value
    )
def extract_cashi_order_id(
    data: Any,
    fallback: str | None = None,
) -> str:
    value = recursive_find(
        data,
        {
            "orderId",
            "order_id",
            "orderID",
            "payment_id",
            "paymentId",
            "transaction_id",
            "transactionId",
        },
    )
    if value:
        return str(
            value
        ).strip()
    return str(
        fallback or ""
    ).strip()
def extract_cashi_qr_url(
    data: Any,
) -> str:
    value = recursive_find(
        data,
        {
            "qrUrl",
            "qr_url",
            "qrURL",
            "qris_url",
            "qrisUrl",
            "qr",
            "qr_code",
            "qrCode",
        },
    )
    if not value:
        return ""
    if isinstance(
        value,
        dict,
    ):
        value = (
            value.get("url")
            or value.get("image")
            or value.get("src")
        )
    return str(
        value or ""
    ).strip()
def extract_cashi_payment_url(
    data: Any,
) -> str:
    value = recursive_find(
        data,
        {
            "checkout_url",
            "checkoutUrl",
            "payment_url",
            "paymentUrl",
            "payment_link",
            "paymentLink",
            "url",
        },
    )
    if not value:
        return ""
    return str(
        value or ""
    ).strip()
def parse_cashi_datetime(
    value: Any,
):
    if value is None:
        return None
    # Cashi memakai "0" untuk no expiration.
    if str(value).strip().lower() in {
        "",
        "0",
        "0.0",
        "none",
        "null",
    }:
        return None
    if isinstance(
        value,
        datetime,
    ):
        if value.tzinfo is None:
            return value.replace(
                tzinfo=timezone.utc
            )
        return value
    try:
        if isinstance(
            value,
            (int, float),
        ):
            # Angka 0 sudah ditangani di atas.
            return datetime.fromtimestamp(
                float(value),
                tz=timezone.utc,
            )
        text = str(
            value
        ).strip()
        if not text:
            return None
        if text.endswith("Z"):
            text = (
                text[:-1]
                + "+00:00"
            )
        result = datetime.fromisoformat(
            text
        )
        if result.tzinfo is None:
            result = result.replace(
                tzinfo=timezone.utc
            )
        return result
    except Exception:
        try:
            return Cashi._parse_datetime(
                value
            )
        except Exception:
            logger.warning(
                (
                    "CASHI DATETIME PARSE FAILED "
                    "| value=%r"
                ),
                value,
                exc_info=True,
            )
            return None
def extract_cashi_expires_at(
    data: Any,
):
    value = recursive_find(
        data,
        {
            "expires_at",
            "expiresAt",
            "expired_at",
            "expiredAt",
            "expiry",
            "expiration",
        },
    )
    return parse_cashi_datetime(
        value
    )
# ============================================================
# CALLBACK TOKEN
# ============================================================
async def create_callback_token(
    prefix: str,
    data: dict,
) -> str:
    token = secrets.token_urlsafe(
        12
    )
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
        data = await safe_get(
            f"cb:{prefix}:{token}"
        )
        if isinstance(
            data,
            dict,
        ):
            return data
        if isinstance(
            data,
            bytes,
        ):
            data = data.decode(
                "utf-8",
                errors="ignore",
            )
        if isinstance(
            data,
            str,
        ):
            try:
                return json.loads(
                    data
                )
            except Exception:
                return None
        return None
    except Exception:
        logger.exception(
            (
                "GET CALLBACK TOKEN ERROR "
                "| prefix=%s"
            ),
            prefix,
        )
        return None
# ============================================================
# MEDIA PARSER
# ============================================================
def parse_media(
    media_data: Any,
) -> list[dict]:
    if not media_data:
        return []
    if isinstance(
        media_data,
        str,
    ):
        try:
            media_data = json.loads(
                media_data
            )
        except Exception:
            logger.warning(
                "MEDIA JSON PARSE ERROR"
            )
            return []
    if isinstance(
        media_data,
        dict,
    ):
        media_data = (
            media_data.get("media")
            or media_data.get("items")
            or media_data.get("messages")
            or []
        )
    if not isinstance(
        media_data,
        list,
    ):
        return []
    result = []
    for item in media_data:
        if isinstance(
            item,
            dict,
        ):
            message_id = (
                item.get("message_id")
                or item.get("messageId")
                or item.get("id")
            )
            try:
                message_id = int(
                    message_id
                )
            except (
                ValueError,
                TypeError,
            ):
                continue
            if message_id <= 0:
                continue
            result.append({
                **item,
                "message_id": message_id,
            })
        else:
            try:
                message_id = int(
                    item
                )
            except (
                ValueError,
                TypeError,
            ):
                continue
            if message_id <= 0:
                continue
            result.append({
                "message_id": message_id,
            })
    return result
# ============================================================
# DATABASE
# ============================================================
async def get_file_by_code(
    code: str,
):
    if not code:
        return None
    code = str(
        code
    ).strip()
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
          AND status IN ('pending','verifying')
        ORDER BY id DESC
        LIMIT 1
        """,
        int(user_id),
        str(code).strip(),
    )
async def get_active_method_purchase(
    user_id: int,
    code: str,
    payment_prefix: str,
):
    return await fetchrow(
        """
        SELECT *
        FROM file_purchases
        WHERE user_id=$1
          AND file_code=$2
          AND status IN ('pending','verifying')
          AND payment_id LIKE $3
        ORDER BY id DESC
        LIMIT 1
        """,
        int(user_id),
        str(code).strip(),
        f"{payment_prefix}%",
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
# PAYMENT METHOD DETECTION
# ============================================================
def purchase_method(
    purchase,
) -> str:
    payment_id = str(
        purchase.get("payment_id")
        or ""
    ).strip()
    if payment_id.startswith(
        "CASHI-"
    ):
        return "cashi"
    if payment_id.startswith(
        "MANUAL-"
    ):
        return "manual"
    return ""
# ============================================================
# DELETE OLD PAYMENT MESSAGE
# ============================================================
async def delete_payment_message(
    bot,
    purchase,
):
    """Best-effort deletion of an old payment message.

    Telegram returns 'message to delete not found' when the message was
    already deleted. That is a normal/idempotent condition, not a payment
    failure, so it is intentionally ignored.
    """
    message_id = purchase.get("qr_message_id")
    chat_id = purchase.get("qr_chat_id")
    if not message_id or not chat_id:
        return False
    try:
        await bot.delete_message(
            chat_id=int(chat_id),
            message_id=int(message_id),
        )
        return True
    except TelegramBadRequest as exc:
        if "message to delete not found" in str(exc).lower():
            logger.info(
                "PAYMENT MESSAGE ALREADY GONE | chat=%s | message=%s",
                chat_id,
                message_id,
            )
            return False
        logger.warning(
            "DELETE PAYMENT MESSAGE FAILED | chat=%s | message=%s",
            chat_id,
            message_id,
            exc_info=True,
        )
        return False
    except Exception:
        logger.warning(
            "DELETE PAYMENT MESSAGE FAILED | chat=%s | message=%s",
            chat_id,
            message_id,
            exc_info=True,
        )
        return False
# ============================================================
# PAYMENT LOADING UI
# ============================================================
def payment_loading_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="⏳ Memproses pembayaran...",
                    callback_data="none",
                )
            ]
        ]
    )


async def show_payment_loading(
    call: CallbackQuery,
    text: str = "⏳ Memproses pembayaran...",
):
    """Give instant visual feedback before slow DB/API operations."""
    try:
        await call.answer(text)
    except Exception:
        pass
    try:
        await call.message.edit_reply_markup(
            reply_markup=payment_loading_keyboard()
        )
    except Exception:
        # Some source messages (photo/media/etc.) may not be editable.
        pass


# ============================================================
# PAYMENT KEYBOARD
# ============================================================
def payment_method_keyboard(
    code: str,
):
    buttons = []
    if AUTO_PAYMENT_ENABLED:
        buttons.append([
            InlineKeyboardButton(
                text="💳 Bayar via Cashi",
                callback_data=f"cashi:{code}",
            )
        ])
    if MANUAL_PAYMENT_ENABLED:
        buttons.append([
            InlineKeyboardButton(
                text="📷 QR Manual",
                callback_data=f"manual:{code}",
            )
        ])
    if not buttons:
        buttons.append([
            InlineKeyboardButton(
                text="❌ Pembayaran Tidak Tersedia",
                callback_data="none",
            )
        ])
    buttons.append([
        InlineKeyboardButton(
            text="❌ Batal",
            callback_data="close",
        )
    ])
    return InlineKeyboardMarkup(
        inline_keyboard=buttons
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
    await show_payment_loading(
        call,
        "⏳ Menyiapkan pembayaran...",
    )
    try:
        code = call.data.split(
            ":",
            1,
        )[1].strip()
    except (
        AttributeError,
        IndexError,
    ):
        return await call.message.answer(
            "❌ Code tidak valid."
        )
    if not code:
        return await call.message.answer(
            "❌ Code tidak valid."
        )
    try:
        file = await get_file_by_code(
            code
        )
    except Exception:
        logger.exception(
            "GET FILE ERROR"
        )
        return await call.message.answer(
            "❌ Gagal mengambil data file."
        )
    if not file:
        return await call.message.answer(
            "❌ File tidak ditemukan."
        )
    price = safe_int(
        file.get("price")
    )
    if price <= 0:
        return await call.message.answer(
            "❌ Harga file tidak valid."
        )
    user_id = int(
        call.from_user.id
    )
    paid = await get_paid_purchase(
        user_id,
        code,
    )
    if paid:
        return await call.message.answer(
            "✅ Kamu sudah membeli file ini."
        )
    # --------------------------------------------------------
    # Jika ada satu active, tampilkan transaksi tersebut.
    # Jika Cashi + Manual sama-sama aktif, tampilkan pilihan
    # metode agar user bisa masuk ke transaksi masing-masing.
    # --------------------------------------------------------
    active_rows = await fetch(
        """
        SELECT *
        FROM file_purchases
        WHERE user_id=$1
          AND file_code=$2
          AND status IN ('pending','verifying')
        ORDER BY id DESC
        LIMIT 10
        """,
        user_id,
        code,
    )
    if active_rows:
        methods = {
            purchase_method(row)
            for row in active_rows
        }
        if methods == {"cashi"}:
            return await show_existing_cashi(
                call,
                active_rows[0],
                file,
            )
        if methods == {"manual"}:
            return await show_existing_manual(
                call,
                active_rows[0],
                file,
            )
        if "cashi" in methods or "manual" in methods:
            await call.message.answer(
                (
                    "⏳ <b>Kamu sudah memiliki pembayaran "
                    "yang sedang aktif.</b>\n\n"
                    "Kamu bisa melanjutkan salah satu "
                    "metode pembayaran di bawah."
                ),
                parse_mode="HTML",
                reply_markup=payment_method_keyboard(
                    code
                ),
            )
            return
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
        reply_markup=payment_method_keyboard(
            code
        ),
    )
# ============================================================
# BUY ALIAS
# ============================================================
@router.callback_query(
    F.data.startswith("buy:")
)
async def buy_payment_alias(
    call: CallbackQuery,
):
    code = call.data.split(
        ":",
        1,
    )[1].strip()
    call.data = f"pay:{code}"
    return await choose_payment(
        call
    )
# ============================================================
# CASHI ENTRY
# ============================================================
@router.callback_query(
    F.data.startswith("cashi:")
)
async def cashi_payment(
    call: CallbackQuery,
):
    await show_payment_loading(
        call,
        "⏳ Menyiapkan Cashi...",
    )
    if not AUTO_PAYMENT_ENABLED:
        return await call.message.answer(
            "❌ Pembayaran Cashi sedang tidak tersedia."
        )
    try:
        code = call.data.split(
            ":",
            1,
        )[1].strip()
    except (
        AttributeError,
        IndexError,
    ):
        return await call.message.answer(
            "❌ Code tidak valid."
        )
    file = await get_file_by_code(
        code
    )
    if not file:
        return await call.message.answer(
            "❌ File tidak ditemukan."
        )
    price = safe_int(
        file.get("price")
    )
    if price <= 0:
        return await call.message.answer(
            "❌ Harga file tidak valid."
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
    await show_payment_loading(
        call,
        "⏳ Menyiapkan QR manual...",
    )
    if not MANUAL_PAYMENT_ENABLED:
        return await call.message.answer(
            "❌ Pembayaran manual sedang tidak tersedia."
        )
    try:
        code = call.data.split(
            ":",
            1,
        )[1].strip()
    except (
        AttributeError,
        IndexError,
    ):
        return await call.message.answer(
            "❌ Code tidak valid."
        )
    file = await get_file_by_code(
        code
    )
    if not file:
        return await call.message.answer(
            "❌ File tidak ditemukan."
        )
    price = safe_int(
        file.get("price")
    )
    if price <= 0:
        return await call.message.answer(
            "❌ Harga file tidak valid."
        )
    return await create_manual_payment(
        call,
        code,
        file,
    )
# ============================================================
# CREATE / REUSE METHOD PURCHASE
# ============================================================
async def get_or_create_purchase(
    user_id: int,
    code: str,
    file,
    payment_prefix: str,
):
    """Return one active purchase, creating it atomically when necessary.

    The UNIQUE(user_id, file_code) constraint is intentional. Two fast
    callbacks can reach this function at the same time, so a read-then-
    INSERT sequence is not safe. INSERT ... ON CONFLICT makes the operation
    idempotent and prevents the duplicate-key error seen in production.
    """
    user_id = int(user_id)
    code = str(code or "").strip()
    payment_prefix = str(payment_prefix or "").strip()

    paid = await get_paid_purchase(user_id, code)
    if paid:
        return {
            "purchase": paid,
            "already_paid": True,
            "existing": True,
        }

    existing = await get_active_method_purchase(
        user_id,
        code,
        payment_prefix,
    )
    if existing:
        return {
            "purchase": existing,
            "already_paid": False,
            "existing": True,
        }

    payment_id = (
        f"{payment_prefix}"
        f"{user_id}-"
        f"{secrets.token_hex(8)}"
    )

    try:
        # IMPORTANT:
        # file_purchases has UNIQUE(user_id, file_code), therefore two
        # simultaneous callbacks must never be allowed to raise an error.
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
                created_at,
                paid_at,
                qr_image,
                payment_url,
                expires_at,
                qr_message_id,
                qr_chat_id,
                media_session_id,
                gateway_order_id
            )
            VALUES
            (
                $1,
                $2,
                $3,
                $4,
                $5,
                'pending',
                NOW(),
                NULL,
                NULL,
                NULL,
                NULL,
                NULL,
                NULL,
                NULL,
                NULL
            )
            ON CONFLICT (user_id, file_code)
            DO NOTHING
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
            "CREATE PURCHASE DB ERROR | user=%s | code=%s | method=%s",
            user_id,
            code,
            payment_prefix,
        )
        # Never create another payment after an unexpected DB error.
        # Re-read the existing transaction before reporting failure.
        existing = await get_active_method_purchase(
            user_id,
            code,
            payment_prefix,
        )
        if existing:
            return {
                "purchase": existing,
                "already_paid": False,
                "existing": True,
            }
        paid = await get_paid_purchase(user_id, code)
        if paid:
            return {
                "purchase": paid,
                "already_paid": True,
                "existing": True,
            }
        return None

    if purchase:
        logger.info(
            "PURCHASE CREATED | id=%s | user=%s | code=%s | method=%s",
            purchase.get("id"),
            user_id,
            code,
            payment_prefix,
        )
        return {
            "purchase": purchase,
            "already_paid": False,
            "existing": False,
        }

    # ON CONFLICT DO NOTHING means another request already owns the
    # unique (user_id, file_code) row. Fetch it instead of attempting
    # another INSERT.
    paid = await get_paid_purchase(user_id, code)
    if paid:
        return {
            "purchase": paid,
            "already_paid": True,
            "existing": True,
        }

    # Because the database intentionally has UNIQUE(user_id, file_code),
    # there can only be one active purchase row for a user/file. If another
    # callback created it first, reuse that row regardless of its method.
    active_any = await fetchrow(
        """
        SELECT *
        FROM file_purchases
        WHERE user_id=$1
          AND file_code=$2
          AND status IN ('pending','verifying')
        ORDER BY id DESC
        LIMIT 1
        """,
        user_id,
        code,
    )
    if active_any:
        logger.info(
            "PURCHASE REUSED AFTER CONFLICT | id=%s | user=%s | code=%s | method=%s",
            active_any.get("id"),
            user_id,
            code,
            purchase_method(active_any),
        )
        return {
            "purchase": active_any,
            "already_paid": False,
            "existing": True,
        }

    # The unique row exists, but it is not active for this payment method.
    # This can happen when an old row is failed/expired/rejected. Do not
    # blindly INSERT because the unique constraint still protects the pair.
    row = await fetchrow(
        """
        SELECT *
        FROM file_purchases
        WHERE user_id=$1
          AND file_code=$2
        ORDER BY
            CASE
                WHEN status='paid' THEN 0
                WHEN status IN ('pending','verifying') THEN 1
                ELSE 2
            END,
            id DESC
        LIMIT 1
        """,
        user_id,
        code,
    )
    if row:
        status = normalize_status(row.get("status"))
        if status in REUSABLE_PURCHASE_STATUSES:
            try:
                reused = await fetchrow(
                    """
                    UPDATE file_purchases
                    SET
                        owner_id=$1,
                        paid_price=$2,
                        payment_id=$3,
                        status='pending',
                        created_at=NOW(),
                        paid_at=NULL,
                        qr_image=NULL,
                        payment_url=NULL,
                        expires_at=NULL,
                        qr_message_id=NULL,
                        qr_chat_id=NULL,
                        media_session_id=NULL,
                        gateway_order_id=NULL
                    WHERE id=$4
                      AND user_id=$5
                      AND file_code=$6
                      AND status IN (
                          'failed',
                          'rejected',
                          'expired',
                          'cancel',
                          'cancelled',
                          'canceled'
                      )
                    RETURNING *
                    """,
                    file.get("owner_id"),
                    safe_int(file.get("price")),
                    payment_id,
                    row["id"],
                    user_id,
                    code,
                )
                if reused:
                    logger.info(
                        "PURCHASE REACTIVATED | id=%s | user=%s | code=%s | method=%s",
                        reused.get("id"),
                        user_id,
                        code,
                        payment_prefix,
                    )
                    return {
                        "purchase": reused,
                        "already_paid": False,
                        "existing": False,
                    }
            except Exception:
                logger.exception(
                    "REACTIVATE PURCHASE ERROR | id=%s | user=%s | code=%s",
                    row.get("id"),
                    user_id,
                    code,
                )

        if status == "paid":
            return {
                "purchase": row,
                "already_paid": True,
                "existing": True,
            }

    logger.error(
        "PURCHASE CONFLICT UNRESOLVED | user=%s | code=%s | method=%s",
        user_id,
        code,
        payment_prefix,
    )
    return None

# ============================================================
# CASHI HEADERS
# ============================================================
def cashi_headers() -> dict:
    return {
        "x-api-key": str(
            CASHI_API_KEY or ""
        ).strip(),
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "MKTPLBot/1.0",
    }
# ============================================================
# CASHI CREATE ORDER
# ============================================================
async def cashi_create_order(
    amount: int,
    order_id: str,
):
    if not CASHI_API_KEY:
        return {
            "ok": False,
            "definitive": True,
            "data": None,
            "error": (
                "CASHI_API_KEY belum dikonfigurasi."
            ),
        }
    payload = {
        "amount": int(amount),
        "order_id": str(order_id),
        "kode_channel": "QRIS_CUSTOM",
    }
    logger.info(
        (
            "CASHI CREATE REQUEST "
            "| order=%s | amount=%s"
        ),
        order_id,
        amount,
    )
    try:
        timeout = aiohttp.ClientTimeout(
            total=35,
            connect=10,
            sock_read=25,
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
                logger.info(
                    (
                        "CASHI CREATE RESPONSE "
                        "| HTTP=%s | BODY=%s"
                    ),
                    response.status,
                    raw_text[:3000],
                )
                try:
                    data = json.loads(
                        raw_text
                    )
                except Exception:
                    return {
                        "ok": False,
                        "definitive": (
                            400
                            <= response.status
                            < 500
                        ),
                        "data": None,
                        "error": (
                            "Response Cashi bukan JSON."
                        ),
                    }
                if (
                    response.status < 200
                    or response.status >= 300
                ):
                    definitive = (
                        400
                        <= response.status
                        < 500
                    )
                    returned_order = (
                        extract_cashi_order_id(
                            data
                        )
                    )
                    if returned_order:
                        definitive = False
                    return {
                        "ok": False,
                        "definitive": definitive,
                        "data": data,
                        "error": (
                            f"HTTP {response.status}"
                        ),
                    }
                success = data.get(
                    "success"
                )
                if success is False:
                    returned_order = (
                        extract_cashi_order_id(
                            data
                        )
                    )
                    if returned_order:
                        return {
                            "ok": True,
                            "definitive": False,
                            "data": data,
                            "error": (
                                "Cashi success=false "
                                "tetapi order ID tersedia."
                            ),
                        }
                    return {
                        "ok": False,
                        "definitive": True,
                        "data": data,
                        "error": (
                            data.get("message")
                            or data.get("error")
                            or "Cashi menolak pembayaran."
                        ),
                    }
                return {
                    "ok": True,
                    "definitive": False,
                    "data": data,
                    "error": None,
                }
    except asyncio.CancelledError:
        raise
    except (
        asyncio.TimeoutError,
        aiohttp.ClientConnectionError,
        aiohttp.ClientPayloadError,
        aiohttp.ServerTimeoutError,
    ):
        logger.exception(
            (
                "CASHI CREATE UNKNOWN RESULT "
                "| order=%s"
            ),
            order_id,
        )
        return {
            "ok": False,
            "definitive": False,
            "data": None,
            "error": (
                "Timeout/koneksi Cashi."
            ),
        }
    except Exception:
        logger.exception(
            (
                "CASHI CREATE ORDER EXCEPTION "
                "| order=%s"
            ),
            order_id,
        )
        return {
            "ok": False,
            "definitive": False,
            "data": None,
            "error": (
                "Error koneksi Cashi."
            ),
        }
# ============================================================
# CASHI CHECK STATUS
# ============================================================
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
        f"{CASHI_BASE_URL}"
        f"/api/check-status/"
        f"{order_id}"
    )
    logger.info(
        "CASHI STATUS REQUEST | order=%s",
        order_id,
    )
    try:
        timeout = aiohttp.ClientTimeout(
            total=25,
            connect=10,
            sock_read=20,
        )
        async with aiohttp.ClientSession(
            timeout=timeout
        ) as session:
            async with session.get(
                url,
                headers=cashi_headers(),
            ) as response:
                raw_text = await response.text()
                logger.info(
                    (
                        "CASHI STATUS RESPONSE "
                        "| HTTP=%s | BODY=%s"
                    ),
                    response.status,
                    raw_text[:3000],
                )
                try:
                    data = json.loads(
                        raw_text
                    )
                except Exception:
                    return None
                if (
                    response.status < 200
                    or response.status >= 300
                ):
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
# DOWNLOAD CASHI QR
# ============================================================
async def download_qr_from_cashi(
    qr_url: str,
) -> bytes | None:
    if not qr_url:
        return None
    qr_url = str(
        qr_url
    ).strip()
    # ========================================================
    # DATA URI
    # ========================================================
    if qr_url.startswith(
        "data:image/"
    ):
        try:
            header, encoded = (
                qr_url.split(
                    ",",
                    1,
                )
            )
            if ";base64" not in (
                header.lower()
            ):
                logger.error(
                    "CASHI QR DATA URI BUKAN BASE64"
                )
                return None
            content = base64.b64decode(
                encoded,
                validate=True,
            )
            if not content:
                logger.error(
                    "CASHI QR DATA URI KOSONG"
                )
                return None
            is_png = content.startswith(
                b"\x89PNG\r\n\x1a\n"
            )
            is_jpeg = content.startswith(
                b"\xff\xd8\xff"
            )
            is_webp = (
                len(content) >= 12
                and content[:4] == b"RIFF"
                and content[8:12] == b"WEBP"
            )
            if not (
                is_png
                or is_jpeg
                or is_webp
            ):
                logger.error(
                    "CASHI QR DATA URI BUKAN IMAGE VALID"
                )
                return None
            logger.info(
                (
                    "CASHI QR DATA URI DECODED "
                    "| size=%s"
                ),
                len(content),
            )
            return content
        except Exception:
            logger.exception(
                "DECODE CASHI QR DATA URI ERROR"
            )
            return None
    # ========================================================
    # HTTP / HTTPS
    # ========================================================
    if not qr_url.startswith(
        (
            "http://",
            "https://",
        )
    ):
        logger.error(
            "INVALID CASHI QR URL | %s",
            qr_url[:200],
        )
        return None
    logger.info(
        "DOWNLOAD CASHI QR | URL=%s",
        qr_url,
    )
    try:
        timeout = aiohttp.ClientTimeout(
            total=30,
            connect=10,
            sock_read=20,
        )
        headers = {
            "User-Agent": (
                "Mozilla/5.0 "
                "(Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 "
                "(KHTML, like Gecko) "
                "Chrome/131.0 Safari/537.36"
            ),
            "Accept": (
                "image/png,"
                "image/jpeg,"
                "image/webp,"
                "image/*,"
                "*/*;q=0.8"
            ),
        }
        async with aiohttp.ClientSession(
            timeout=timeout
        ) as session:
            async with session.get(
                qr_url,
                headers=headers,
                allow_redirects=True,
            ) as response:
                content = await response.read()
                content_type = (
                    response.headers.get(
                        "Content-Type",
                        "",
                    )
                    .lower()
                    .strip()
                )
                logger.info(
                    (
                        "CASHI QR RESPONSE "
                        "| HTTP=%s | TYPE=%s "
                        "| SIZE=%s | FINAL_URL=%s"
                    ),
                    response.status,
                    content_type,
                    len(content),
                    str(response.url),
                )
                if response.status != 200:
                    logger.error(
                        (
                            "CASHI QR DOWNLOAD FAILED "
                            "| HTTP=%s"
                        ),
                        response.status,
                    )
                    return None
                if not content:
                    return None
                is_png = content.startswith(
                    b"\x89PNG"
                )
                is_jpeg = content.startswith(
                    b"\xff\xd8\xff"
                )
                is_webp = (
                    content.startswith(
                        b"RIFF"
                    )
                    and content[8:12]
                    == b"WEBP"
                )
                if (
                    "image/" not in content_type
                    and not is_png
                    and not is_jpeg
                    and not is_webp
                ):
                    logger.error(
                        (
                            "CASHI QR RESPONSE "
                            "BUKAN IMAGE | TYPE=%s"
                        ),
                        content_type,
                    )
                    return None
                return content
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception(
            "DOWNLOAD CASHI QR EXCEPTION"
        )
        return None
# ============================================================
# SEND CASHI QR
# ============================================================
async def send_cashi_qr(
    message: Message,
    qr_url: str,
    caption: str,
    reply_markup=None,
):
    qr_bytes = await download_qr_from_cashi(
        qr_url
    )
    if not qr_bytes:
        return None
    try:
        photo = BufferedInputFile(
            qr_bytes,
            filename="cashi_qris.png",
        )
        sent = await message.answer_photo(
            photo=photo,
            caption=caption,
            parse_mode="HTML",
            reply_markup=reply_markup,
        )
        logger.info(
            (
                "CASHI QR SENT "
                "| message_id=%s"
            ),
            sent.message_id,
        )
        return sent
    except Exception:
        logger.exception(
            "TELEGRAM SEND CASHI QR ERROR"
        )
        return None
# ============================================================
# CASHI PAYMENT KEYBOARD
# ============================================================
async def payment_check_keyboard(
    code: str,
    purchase_id: int,
):
    token = await create_callback_token(
        "paymentcheck",
        {
            "code": str(code).strip(),
            "purchase_id": int(
                purchase_id
            ),
        },
    )
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔄 Cek Pembayaran",
                    callback_data=(
                        f"paymentcheck:{token}"
                    ),
                )
            ],
            [
                InlineKeyboardButton(
                    text="❌ Tutup",
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
                    callback_data=(
                        f"manualcheck:{token}"
                    ),
                )
            ],
            [
                InlineKeyboardButton(
                    text="❌ Tutup",
                    callback_data="close",
                )
            ],
        ]
    )
# ============================================================
# SHOW EXISTING CASHI
# ============================================================
async def show_existing_cashi(
    call: CallbackQuery,
    purchase,
    file,
):
    purchase_id = safe_int(
        purchase.get("id")
    )
    if purchase_id <= 0:
        return await call.message.answer(
            "❌ ID transaksi tidak valid."
        )
    gateway_order_id = str(
        purchase.get(
            "gateway_order_id"
        )
        or ""
    ).strip()
    # Compatibility dengan transaksi lama:
    # sebelum gateway_order_id ditambahkan, payment_id
    # bisa saja berisi order Cashi.
    if not gateway_order_id:
        payment_id = str(
            purchase.get(
                "payment_id"
            )
            or ""
        ).strip()
        if (
            not payment_id.startswith(
                "CASHI-"
            )
            and payment_id
        ):
            gateway_order_id = payment_id
    if not gateway_order_id:
        return await call.message.answer(
            "❌ ID pembayaran Cashi tidak valid."
        )
    status_data = await cashi_check_status(
        gateway_order_id
    )
    if status_data:
        status = extract_cashi_status(
            status_data
        )
        if status in SUCCESS_STATUSES:
            return await process_existing_success(
                call,
                purchase,
                file,
            )
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
                purchase_id,
            )
            if changed:
                return await call.message.answer(
                    (
                        "⚠️ <b>Pembayaran Cashi sebelumnya "
                        "gagal/expired.</b>\n\n"
                        "Silakan pilih metode pembayaran baru."
                    ),
                    parse_mode="HTML",
                    reply_markup=payment_method_keyboard(
                        file["code"]
                    ),
                )
    qr_url = str(
        purchase.get("qr_image")
        or ""
    ).strip()
    payment_url = str(
        purchase.get("payment_url")
        or ""
    ).strip()
    keyboard = await payment_check_keyboard(
        file["code"],
        purchase_id,
    )
    price = safe_int(
        file.get("price")
    )
    caption = (
        "💳 <b>PEMBAYARAN CASHI</b>\n\n"
        f"📄 <b>{clean_html(file.get('title'))}</b>\n\n"
        f"🔑 Code:\n"
        f"<code>{clean_html(file['code'])}</code>\n\n"
        f"💰 <b>{format_rupiah(price)}</b>\n\n"
        "Scan QR di atas.\n"
        "Setelah membayar, tekan "
        "<b>🔄 Cek Pembayaran</b>.\n\n"
        "⚠️ Jangan melakukan pembayaran dua kali."
    )
    if qr_url:
        sent = await send_cashi_qr(
            call.message,
            qr_url,
            caption,
            keyboard,
        )
        if sent:
            await execute(
                """
                UPDATE file_purchases
                SET
                    qr_message_id=$1,
                    qr_chat_id=$2
                WHERE id=$3
                  AND status='pending'
                """,
                sent.message_id,
                sent.chat.id,
                purchase_id,
            )
            return
        if payment_url:
            await call.message.answer(
                (
                    "⚠️ <b>QR tidak dapat ditampilkan.</b>\n\n"
                    "Pembayaran Cashi tetap aktif."
                ),
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            InlineKeyboardButton(
                                text="💳 Buka Pembayaran",
                                url=payment_url,
                            )
                        ],
                        [
                            keyboard.inline_keyboard[0][0]
                        ],
                    ]
                ),
            )
            return
    if payment_url:
        await call.message.answer(
            (
                "💳 <b>PEMBAYARAN CASHI</b>\n\n"
                f"📄 <b>{clean_html(file.get('title'))}</b>\n\n"
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
                            text="❌ Tutup",
                            callback_data="close",
                        )
                    ],
                ]
            ),
        )
        return
    await call.message.answer(
        (
            "⚠️ <b>Pembayaran Cashi sudah dibuat.</b>\n\n"
            "QR/link pembayaran belum tersedia.\n\n"
            "❗ Jangan membuat transaksi baru.\n"
            "Silakan coba cek kembali beberapa saat lagi."
        ),
        parse_mode="HTML",
        reply_markup=keyboard,
    )
# ============================================================
# SHOW EXISTING MANUAL
# ============================================================
async def show_existing_manual(
    call: CallbackQuery,
    purchase,
    file,
):
    if not MANUAL_PAYMENT_ENABLED:
        return await call.message.answer(
            "❌ QR manual sedang tidak tersedia."
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
                f"🔑 Code:\n"
                f"<code>{clean_html(file['code'])}</code>\n\n"
                f"💰 <b>{format_rupiah(price)}</b>\n\n"
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
        return await call.message.answer(
            "❌ Gagal mengirim QR manual."
        )
# ============================================================
# CREATE CASHI PAYMENT
# ============================================================
async def create_cashi_payment(
    call: CallbackQuery,
    code: str,
    file,
):
    if not AUTO_PAYMENT_ENABLED:
        return await call.message.answer(
            "❌ Pembayaran Cashi sedang tidak tersedia."
        )
    user_id = int(
        call.from_user.id
    )
    price = safe_int(
        file.get("price")
    )
    paid = await get_paid_purchase(
        user_id,
        code,
    )
    if paid:
        return await call.message.answer(
            "✅ Kamu sudah membeli file ini."
        )
    # --------------------------------------------------------
    # ONLY CASHI ACTIVE
    # --------------------------------------------------------
    existing = await get_active_method_purchase(
        user_id,
        code,
        "CASHI-",
    )
    if existing:
        return await show_existing_cashi(
            call,
            existing,
            file,
        )
    # Manual active TIDAK memblokir Cashi.
    # Ini inti perubahan arsitektur.
    result = await get_or_create_purchase(
        user_id=user_id,
        code=code,
        file=file,
        payment_prefix="CASHI-",
    )
    if not result:
        return await call.message.answer(
            "❌ Gagal membuat transaksi pembayaran."
        )
    purchase = result["purchase"]
    if result.get(
        "already_paid"
    ):
        return await call.message.answer(
            "✅ Kamu sudah membeli file ini."
        )
    if result.get("existing"):
        existing_method = purchase_method(purchase)
        if existing_method == "manual":
            return await show_existing_manual(
                call,
                purchase,
                file,
            )
        if existing_method == "cashi":
            return await show_existing_cashi(
                call,
                purchase,
                file,
            )
        logger.warning(
            "UNKNOWN EXISTING PAYMENT METHOD | purchase=%s | payment_id=%s",
            purchase.get("id"),
            purchase.get("payment_id"),
        )
        return await call.message.answer(
            "⚠️ Transaksi pembayaran sudah ada. Silakan gunakan transaksi tersebut."
        )
    payment_id = str(
        purchase.get("payment_id")
        or ""
    ).strip()
    if not payment_id.startswith(
        "CASHI-"
    ):
        return await call.message.answer(
            "❌ ID transaksi Cashi tidak valid."
        )
    # Loading state was shown immediately by the callback entry handler.
    # Keep the original message disabled while the gateway request runs.
    try:
        await call.message.edit_reply_markup(
            reply_markup=payment_loading_keyboard()
        )
    except Exception:
        pass
    # --------------------------------------------------------
    # CREATE CASHI
    # --------------------------------------------------------
    result_cashi = await cashi_create_order(
        amount=price,
        order_id=payment_id,
    )
    if not result_cashi.get(
        "ok"
    ):
        if result_cashi.get(
            "definitive"
        ):
            logger.warning(
                (
                    "CASHI DEFINITIVE FAILED "
                    "| purchase=%s | local=%s "
                    "| error=%s"
                ),
                purchase["id"],
                payment_id,
                result_cashi.get("error"),
            )
            await execute(
                """
                UPDATE file_purchases
                SET status='failed'
                WHERE id=$1
                  AND status='pending'
                  AND payment_id=$2
                """,
                purchase["id"],
                payment_id,
            )
            return await call.message.answer(
                (
                    "❌ <b>Pembayaran Cashi gagal dibuat.</b>\n\n"
                    "Silakan pilih metode pembayaran lain."
                ),
                parse_mode="HTML",
                reply_markup=payment_method_keyboard(
                    code
                ),
            )
        # Unknown result:
        # JANGAN fallback manual.
        keyboard = await payment_check_keyboard(
            code,
            purchase["id"],
        )
        return await call.message.answer(
            (
                "⚠️ <b>Cashi belum memberikan hasil yang pasti.</b>\n\n"
                "Transaksi tetap disimpan dan "
                "<b>tidak dibuat ulang</b> untuk mencegah "
                "pembayaran ganda.\n\n"
                "Silakan tunggu beberapa saat lalu tekan "
                "<b>🔄 Cek Pembayaran</b>."
            ),
            parse_mode="HTML",
            reply_markup=keyboard,
        )
    cashi_data = (
        result_cashi.get("data")
        or {}
    )
    cashi_order_id = extract_cashi_order_id(
        cashi_data
    )
    if not cashi_order_id:
        # Kalau API tidak mengembalikan order ID,
        # kita tidak boleh mengarang order ID baru.
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
                "❌ Cashi tidak mengembalikan "
                "ID transaksi yang valid."
            ),
            reply_markup=payment_method_keyboard(
                code
            ),
        )
    qr_url = extract_cashi_qr_url(
        cashi_data
    )
    payment_url = extract_cashi_payment_url(
        cashi_data
    )
    expires_at = extract_cashi_expires_at(
        cashi_data
    )
    logger.info(
        (
            "CASHI CREATED | purchase=%s "
            "| local=%s | gateway=%s "
            "| qr=%s | url=%s | expires=%s"
        ),
        purchase["id"],
        payment_id,
        cashi_order_id,
        bool(qr_url),
        bool(payment_url),
        expires_at,
    )
    # --------------------------------------------------------
    # SAVE CASHI DATA
    # --------------------------------------------------------
    try:
        saved = await fetchrow(
            """
            UPDATE file_purchases
            SET
                gateway_order_id=$1,
                qr_image=$2,
                payment_url=$3,
                expires_at=$4
            WHERE id=$5
              AND status='pending'
              AND payment_id=$6
            RETURNING *
            """,
            cashi_order_id,
            qr_url or None,
            payment_url or None,
            expires_at,
            purchase["id"],
            payment_id,
        )
    except Exception:
        logger.exception(
            (
                "SAVE CASHI DATA ERROR "
                "| purchase=%s"
            ),
            purchase["id"],
        )
        return await call.message.answer(
            (
                "⚠️ Pembayaran Cashi sudah dibuat, "
                "tetapi data transaksi gagal disimpan."
            ),
            parse_mode="HTML",
        )
    if not saved:
        return await call.message.answer(
            (
                "❌ Transaksi Cashi berubah saat diproses.\n"
                "Silakan cek kembali pembayaran."
            ),
            parse_mode="HTML",
        )
    keyboard = await payment_check_keyboard(
        code,
        saved["id"],
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
    if qr_url:
        sent_message = await send_cashi_qr(
            call.message,
            qr_url,
            caption,
            keyboard,
        )
        if sent_message:
            await execute(
                """
                UPDATE file_purchases
                SET
                    qr_message_id=$1,
                    qr_chat_id=$2
                WHERE id=$3
                  AND status='pending'
                """,
                sent_message.message_id,
                sent_message.chat.id,
                saved["id"],
            )
            return
        logger.error(
            (
                "CASHI QR FAILED TO SEND "
                "| purchase=%s"
            ),
            saved["id"],
        )
    if payment_url:
        await call.message.answer(
            (
                f"{caption}\n\n"
                "⚠️ QR tidak dapat ditampilkan.\n"
                "Gunakan tombol <b>Bayar Sekarang</b>."
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
                            text="❌ Tutup",
                            callback_data="close",
                        )
                    ],
                ]
            ),
        )
        return
    await call.message.answer(
        (
            "⚠️ <b>Pembayaran Cashi sudah dibuat.</b>\n\n"
            "QR/link belum dapat dikirim.\n\n"
            "❗ Jangan melakukan pembayaran kedua.\n"
            "Tekan <b>🔄 Cek Pembayaran</b> setelah beberapa saat."
        ),
        parse_mode="HTML",
        reply_markup=keyboard,
    )
# ============================================================
# CREATE MANUAL PAYMENT
# ============================================================
async def create_manual_payment(
    call: CallbackQuery,
    code: str,
    file,
):
    if not MANUAL_PAYMENT_ENABLED:
        return await call.message.answer(
            "❌ QR manual belum dikonfigurasi."
        )
    user_id = int(
        call.from_user.id
    )
    paid = await get_paid_purchase(
        user_id,
        code,
    )
    if paid:
        return await call.message.answer(
            "✅ Kamu sudah membeli file ini."
        )
    # ONLY MANUAL ACTIVE.
    # Cashi aktif tetap boleh bersamaan.
    existing = await get_active_method_purchase(
        user_id,
        code,
        "MANUAL-",
    )
    if existing:
        return await show_existing_manual(
            call,
            existing,
            file,
        )
    result = await get_or_create_purchase(
        user_id=user_id,
        code=code,
        file=file,
        payment_prefix="MANUAL-",
    )
    if not result:
        return await call.message.answer(
            "❌ Gagal membuat transaksi."
        )
    purchase = result["purchase"]
    if result.get(
        "already_paid"
    ):
        return await call.message.answer(
            "✅ Kamu sudah membeli file ini."
        )
    if result.get("existing"):
        existing_method = purchase_method(purchase)
        if existing_method == "cashi":
            return await show_existing_cashi(
                call,
                purchase,
                file,
            )
        if existing_method == "manual":
            return await show_existing_manual(
                call,
                purchase,
                file,
            )
        logger.warning(
            "UNKNOWN EXISTING PAYMENT METHOD | purchase=%s | payment_id=%s",
            purchase.get("id"),
            purchase.get("payment_id"),
        )
        return await call.message.answer(
            "⚠️ Transaksi pembayaran sudah ada. Silakan gunakan transaksi tersebut."
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
    if not MANUAL_PAYMENT_ENABLED:
        return await call.message.answer(
            "❌ QR manual belum tersedia."
        )
    code = str(
        file.get("code")
        or ""
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
# CLAIM PURCHASE PAID
# ============================================================
async def claim_purchase_paid(
    purchase_id: int,
    user_id: int,
    file_code: str,
    allowed_statuses: tuple = (
        "pending",
        "verifying",
    ),
):
    purchase_id = int(
        purchase_id
    )
    user_id = int(
        user_id
    )
    file_code = str(
        file_code
    ).strip()
    if not purchase_id:
        return None
    placeholders = ",".join(
        f"'{status}'"
        for status in allowed_statuses
    )
    query = f"""
        UPDATE file_purchases
        SET
            status='paid',
            paid_at=COALESCE(
                paid_at,
                NOW()
            )
        WHERE id=$1
          AND user_id=$2
          AND file_code=$3
          AND status IN ({placeholders})
          AND NOT EXISTS (
              SELECT 1
              FROM file_purchases p2
              WHERE p2.user_id=$2
                AND p2.file_code=$3
                AND p2.status='paid'
                AND p2.id<>$1
          )
        RETURNING *
    """
    try:
        updated = await fetchrow(
            query,
            purchase_id,
            user_id,
            file_code,
        )
        if updated:
            return updated
        logger.info(
            (
                "PAYMENT CLAIM LOST "
                "| purchase=%s | user=%s | code=%s"
            ),
            purchase_id,
            user_id,
            file_code,
        )
        return None
    except Exception as exc:
        error_text = str(
            exc
        ).lower()
        if (
            "uq_file_purchases_one_paid"
            in error_text
        ) or (
            "duplicate key"
            in error_text
        ):
            logger.warning(
                (
                    "PAYMENT ALREADY WON "
                    "| purchase=%s"
                ),
                purchase_id,
            )
            return None
        logger.exception(
            "CLAIM PAYMENT ERROR"
        )
        raise
# ============================================================
# CANCEL OTHER PAYMENT ATTEMPTS
# ============================================================
async def cancel_other_active_payments(
    user_id: int,
    file_code: str,
    winner_id: int,
):
    try:
        await execute(
            """
            UPDATE file_purchases
            SET status='cancelled'
            WHERE user_id=$1
              AND file_code=$2
              AND id<>$3
              AND status IN (
                  'pending',
                  'verifying'
              )
            """,
            int(user_id),
            str(file_code).strip(),
            int(winner_id),
        )
    except Exception:
        logger.exception(
            (
                "CANCEL OTHER PAYMENTS ERROR "
                "| winner=%s"
            ),
            winner_id,
        )
# ============================================================
# CASHI PAYMENT CHECK
# ============================================================
@router.callback_query(
    F.data.startswith("paymentcheck:")
)
async def check_cashi_payment(
    call: CallbackQuery,
):
    await call.answer(
        "🔄 Mengecek pembayaran..."
    )
    try:
        token = call.data.split(
            ":",
            1,
        )[1].strip()
    except (
        AttributeError,
        IndexError,
    ):
        return await call.message.answer(
            "❌ Permintaan tidak valid."
        )
    data = await get_callback_token(
        "paymentcheck",
        token,
    )
    if not data:
        return await call.message.answer(
            "❌ Tombol pembayaran sudah expired."
        )
    code = str(
        data.get("code")
        or ""
    ).strip()
    purchase_id = safe_int(
        data.get("purchase_id")
    )
    if not code or purchase_id <= 0:
        return await call.message.answer(
            "❌ Data pembayaran tidak valid."
        )
    user_id = int(
        call.from_user.id
    )
    lock_key = (
        f"cashi-check:"
        f"{user_id}:"
        f"{purchase_id}"
    )
    try:
        if await safe_get(
            lock_key
        ):
            return await call.message.answer(
                "⏳ Pembayaran sedang dicek..."
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
    purchase = await fetchrow(
        """
        SELECT *
        FROM file_purchases
        WHERE id=$1
          AND user_id=$2
          AND file_code=$3
        LIMIT 1
        """,
        purchase_id,
        user_id,
        code,
    )
    if not purchase:
        return await call.message.answer(
            "❌ Transaksi tidak ditemukan."
        )
    method = purchase_method(
        purchase
    )
    if method != "cashi":
        return await call.message.answer(
            "❌ Ini bukan transaksi Cashi."
        )
    current_status = normalize_status(
        purchase.get("status")
    )
    if current_status == "paid":
        return await call.message.answer(
            "✅ Pembayaran ini sudah berhasil diproses."
        )
    if current_status not in {
        "pending",
        "verifying",
    }:
        return await call.message.answer(
            (
                "ℹ️ Transaksi sudah tidak berada "
                "dalam status pembayaran aktif."
            )
        )
    gateway_order_id = str(
        purchase.get(
            "gateway_order_id"
        )
        or ""
    ).strip()
    # Compatibility transaksi lama.
    if not gateway_order_id:
        old_payment_id = str(
            purchase.get(
                "payment_id"
            )
            or ""
        ).strip()
        if old_payment_id:
            gateway_order_id = old_payment_id
    if not gateway_order_id:
        return await call.message.answer(
            "❌ Gateway order ID tidak ditemukan."
        )
    status_data = await cashi_check_status(
        gateway_order_id
    )
    if not status_data:
        return await call.message.answer(
            (
                "⚠️ <b>Cashi belum dapat dihubungi.</b>\n\n"
                "Transaksi tetap aktif.\n"
                "Silakan coba lagi beberapa saat."
            ),
            parse_mode="HTML",
        )
    status = extract_cashi_status(
        status_data
    )
    logger.info(
        (
            "CASHI STATUS PARSED "
            "| purchase=%s | gateway=%s "
            "| status=%s"
        ),
        purchase["id"],
        gateway_order_id,
        status,
    )
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
    if status in FAILED_STATUSES:
        changed = await fetchrow(
            """
            UPDATE file_purchases
            SET status=$1
            WHERE id=$2
              AND status IN ('pending','verifying')
            RETURNING *
            """,
            status,
            purchase_id,
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
                "Silakan melakukan pembayaran baru."
            ),
            parse_mode="HTML",
            reply_markup=payment_method_keyboard(
                code
            ),
        )
    return await call.message.answer(
        (
            "⏳ <b>Pembayaran belum terkonfirmasi.</b>\n\n"
            "Cashi belum memberikan status berhasil.\n\n"
            "Jika kamu sudah membayar, tunggu beberapa detik "
            "kemudian tekan <b>🔄 Cek Pembayaran</b> lagi.\n\n"
            "⚠️ Jangan membayar ulang."
        ),
        parse_mode="HTML",
    )
# ============================================================
# PROCESS SUCCESS
# ============================================================
async def process_existing_success(
    call: CallbackQuery,
    purchase,
    file,
):
    user_id = safe_int(
        purchase.get("user_id")
    )
    # Jangan kirim "berhasil" sebelum transaksi benar-benar
    # memenangkan claim paid.
    return await finish_payment(
        call.bot,
        purchase,
        file,
        purchase.get("payment_id"),
        call.message,
    )
# ============================================================
# COMMON SUCCESS SIDE EFFECTS
# ============================================================
async def complete_success_side_effects(
    bot,
    purchase,
    file,
    invoice,
    message,
    media_list,
):
    purchase_id = safe_int(
        purchase.get("id")
    )
    user_id = safe_int(
        purchase.get("user_id")
    )
    code = str(
        file.get("code")
        or ""
    ).strip()
    # ========================================================
    # MEDIA SESSION
    # ========================================================
    media_id = secrets.token_hex(
        16
    )
    session_data = {
        "user_id": user_id,
        "media": media_list,
        "share_media": bool(
            file.get(
                "share_media",
                False,
            )
        ),
        "invoice": invoice,
        "purchase_id": purchase_id,
    }
    try:
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
              AND status='paid'
            """,
            media_id,
            purchase_id,
        )
    except Exception:
        logger.exception(
            "MEDIA SESSION CREATE ERROR"
        )
        return False
    # ========================================================
    # BUY COUNT
    # ========================================================
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
            code,
        )
    except Exception:
        logger.exception(
            "BUY COUNT UPDATE ERROR"
        )
    # ========================================================
    # FREE CODE PROGRESS
    # ========================================================
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
            code,
            user_id,
        )
        for row in completed_rows:
            if row["completed"]:
                try:
                    await bot.send_message(
                        row["user_id"],
                        (
                            "🎉 <b>Progress Code Free 3/3!</b>\n\n"
                            f"Code "
                            f"<code>{clean_html(code)}</code>\n"
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
            "FREE CODE PROGRESS ERROR"
        )
    # ========================================================
    # SELLER PROFIT
    # ========================================================
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
                f"Pendapatan file {code}",
            )
    except Exception:
        logger.exception(
            "SELLER PROFIT ERROR"
        )
    # ========================================================
    # NOTIFICATION CHANNEL
    # ========================================================
    try:
        if NOTIF_CHANNEL_ID:
            masked = mask_user_id(
                user_id
            )
            buy_url = (
                "https://t.me/mktplbot"
                f"?start={code}"
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
            payment_name = (
                "CASHI"
                if purchase_method(
                    purchase
                ) == "cashi"
                else "MANUAL"
            )
            await bot.send_message(
                NOTIF_CHANNEL_ID,
                (
                    "💸 <b>FILE PAYMENT SUCCESS</b>\n\n"
                    f"📄 Judul: "
                    f"<b>{clean_html(file.get('title'))}</b>\n"
                    f"📁 Code: "
                    f"<code>{clean_html(code)}</code>\n"
                    f"👤 User: "
                    f"<code>{masked}</code>\n"
                    f"💰 Harga: "
                    f"<b>{format_rupiah(purchase.get('paid_price'))}</b>\n"
                    f"💳 Payment: <b>{payment_name}</b>"
                ),
                parse_mode="HTML",
                reply_markup=keyboard,
            )
    except Exception:
        logger.exception(
            "PAYMENT NOTIFICATION ERROR"
        )
    # ========================================================
    # DELETE PAYMENT QR
    # ========================================================
    await delete_payment_message(
        bot,
        purchase,
    )
    # ========================================================
    # USER SUCCESS MESSAGE
    # ========================================================
    try:
        await message.answer(
            (
                "🎉 <b>Pembayaran berhasil!</b>\n\n"
                f"📦 Total File: <b>{len(media_list)}</b>\n\n"
                "Silakan pilih pengiriman:"
            ),
            parse_mode="HTML",
            reply_markup=media_keyboard(
                media_id,
                1,
                len(media_list),
            ),
        )
    except Exception:
        logger.exception(
            "SEND MEDIA MENU ERROR"
        )
    return True
# ============================================================
# FINISH CASHI PAYMENT
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
    user_id = safe_int(
        purchase.get("user_id")
    )
    code = str(
        file.get("code")
        or purchase.get("file_code")
        or ""
    ).strip()
    if (
        purchase_id <= 0
        or user_id <= 0
        or not code
    ):
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
        # CLAIM PAYMENT
        # ----------------------------------------------------
        updated = await claim_purchase_paid(
            purchase_id,
            user_id,
            code,
            allowed_statuses=(
                "pending",
                "verifying",
            ),
        )
        if not updated:
            paid = await get_paid_purchase(
                user_id,
                code,
            )
            if paid:
                return await message.answer(
                    "✅ Pembayaran sudah diproses sebelumnya."
                )
            return False
        purchase = updated
        # ----------------------------------------------------
        # CANCEL OTHER PAYMENT METHODS
        # ----------------------------------------------------
        await cancel_other_active_payments(
            user_id,
            code,
            purchase_id,
        )
        # ----------------------------------------------------
        # SUCCESS MESSAGE
        # ----------------------------------------------------
        try:
            await message.answer(
                (
                    "⏳ <b>Pembayaran berhasil terdeteksi.</b>\n\n"
                    "Sedang memproses file..."
                ),
                parse_mode="HTML",
            )
        except Exception:
            pass
        return await complete_success_side_effects(
            bot,
            purchase,
            file,
            invoice,
            message,
            media_list,
        )
    except Exception:
        logger.exception(
            (
                "FINISH PAYMENT ERROR "
                "| purchase=%s"
            ),
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
    await call.answer(
        "⏳ Mengirim permintaan verifikasi..."
    )
    try:
        token = call.data.split(
            ":",
            1,
        )[1].strip()
    except (
        AttributeError,
        IndexError,
    ):
        return await call.message.answer(
            "❌ Permintaan tidak valid."
        )
    callback_data = await get_callback_token(
        "manualcheck",
        token,
    )
    if not callback_data:
        return await call.message.answer(
            "❌ Tombol sudah expired."
        )
    code = str(
        callback_data.get("code")
        or ""
    ).strip()
    user_id = int(
        call.from_user.id
    )
    purchase = await get_active_method_purchase(
        user_id,
        code,
        "MANUAL-",
    )
    if not purchase:
        paid = await get_paid_purchase(
            user_id,
            code,
        )
        if paid:
            return await call.message.answer(
                "✅ Pembayaran sudah diverifikasi."
            )
        return await call.message.answer(
            "❌ Transaksi manual tidak ditemukan."
        )
    payment_id = str(
        purchase.get("payment_id")
        or ""
    ).strip()
    if not payment_id.startswith(
        "MANUAL-"
    ):
        return await call.message.answer(
            "❌ Transaksi ini bukan pembayaran manual."
        )
    purchase_id = safe_int(
        purchase.get("id")
    )
    lock_key = (
        f"manualverify:{purchase_id}"
    )
    try:
        if await safe_get(
            lock_key
        ):
            return await call.message.answer(
                (
                    "⏳ Permintaan verifikasi sudah "
                    "dikirim ke admin."
                )
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
        return await call.message.answer(
            "❌ File tidak ditemukan."
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
                    callback_data=(
                        f"approve:{purchase_id}"
                    ),
                ),
                InlineKeyboardButton(
                    text="❌ Reject",
                    callback_data=(
                        f"reject:{purchase_id}"
                    ),
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
                (
                    "SEND MANUAL ADMIN ERROR "
                    "| admin=%s"
                ),
                admin_id,
            )
    if sent == 0:
        return await call.message.answer(
            (
                "❌ Tidak ada admin yang dapat "
                "menerima permintaan."
            )
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
    await call.answer(
        "⏳ Memproses pembayaran..."
    )
    await state.clear()
    try:
        purchase_id = int(
            call.data.split(
                ":",
                1,
            )[1]
        )
    except (
        ValueError,
        IndexError,
    ):
        return await call.message.answer(
            "❌ ID transaksi tidak valid."
        )
    # --------------------------------------------------------
    # VERIFY MANUAL
    # --------------------------------------------------------
    purchase = await fetchrow(
        """
        UPDATE file_purchases
        SET status='verifying'
        WHERE id=$1
          AND status='pending'
          AND payment_id LIKE 'MANUAL-%'
        RETURNING *
        """,
        purchase_id,
    )
    if not purchase:
        current = await get_purchase_by_id(
            purchase_id
        )
        if current and current.get(
            "status"
        ) == "paid":
            return await call.message.answer(
                "✅ Pembayaran sudah diproses admin lain."
            )
        if current and current.get(
            "status"
        ) == "rejected":
            return await call.message.answer(
                "❌ Pembayaran sudah ditolak."
            )
        if current and current.get(
            "status"
        ) == "cancelled":
            return await call.message.answer(
                (
                    "ℹ️ Pembayaran ini dibatalkan karena "
                    "metode pembayaran lain sudah berhasil."
                )
            )
        return await call.message.answer(
            "❌ Transaksi sudah diproses / tidak valid."
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
        return await call.message.answer(
            "❌ File tidak ditemukan."
        )
    user_id = safe_int(
        purchase.get("user_id")
    )
    try:
        user_message = await call.bot.send_message(
            user_id,
            (
                "⏳ <b>Pembayaran manual disetujui.</b>\n\n"
                "Sedang memproses file..."
            ),
            parse_mode="HTML",
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
        return await call.message.answer(
            "❌ User tidak dapat dihubungi."
        )
    success = await finish_manual_payment(
        call.bot,
        purchase,
        file,
        purchase.get("payment_id"),
        user_message,
    )
    if not success:
        current = await get_purchase_by_id(
            purchase_id
        )
        if current and current.get(
            "status"
        ) == "paid":
            return await call.message.answer(
                (
                    "ℹ️ Pembayaran sudah dimenangkan "
                    "oleh transaksi lain."
                )
            )
        return await call.message.answer(
            "❌ Pembayaran gagal diproses."
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
# FINISH MANUAL PAYMENT
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
    user_id = safe_int(
        purchase.get("user_id")
    )
    code = str(
        file.get("code")
        or purchase.get("file_code")
        or ""
    ).strip()
    if (
        purchase_id <= 0
        or user_id <= 0
        or not code
    ):
        return False
    try:
        media_list = parse_media(
            file.get("media")
        )
        if not media_list:
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
        # CLAIM
        # ----------------------------------------------------
        updated = await claim_purchase_paid(
            purchase_id,
            user_id,
            code,
            allowed_statuses=(
                "verifying",
                "pending",
            ),
        )
        if not updated:
            paid = await get_paid_purchase(
                user_id,
                code,
            )
            if paid:
                return False
            logger.warning(
                (
                    "MANUAL PAYMENT CLAIM LOST "
                    "| purchase=%s"
                ),
                purchase_id,
            )
            return False
        purchase = updated
        # ----------------------------------------------------
        # CANCEL CASHI / OTHER ACTIVE
        # ----------------------------------------------------
        await cancel_other_active_payments(
            user_id,
            code,
            purchase_id,
        )
        return await complete_success_side_effects(
            bot,
            purchase,
            file,
            invoice,
            message,
            media_list,
        )
    except Exception:
        logger.exception(
            (
                "FINISH MANUAL PAYMENT ERROR "
                "| purchase=%s"
            ),
            purchase_id,
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
    except (
        ValueError,
        IndexError,
    ):
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
            (
                "❌ Transaksi tidak ditemukan "
                "atau sudah diproses."
            ),
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
            f"📦 Code: "
            f"<code>{clean_html(purchase['file_code'])}</code>\n\n"
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
        rejected.get("file_code")
        or ""
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
                chat_id=int(
                    qr_chat_id
                ),
                message_id=int(
                    qr_message_id
                ),
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
                    f"📦 Code: "
                    f"<code>{clean_html(code)}</code>\n\n"
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
            f"📦 Code: "
            f"<code>{clean_html(code)}</code>\n\n"
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
        "Ditutup."
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
    if isinstance(
        data,
        str,
    ):
        try:
            data = json.loads(
                data
            )
        except Exception:
            await call.answer(
                "❌ Data session tidak valid.",
                show_alert=True,
            )
            return None
    if not isinstance(
        data,
        dict,
    ):
        await call.answer(
            "❌ Data session tidak valid.",
            show_alert=True,
        )
        return None
    session_user_id = data.get(
        "user_id"
    )
    try:
        if int(
            session_user_id
        ) != int(
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
        (
            total
            + PER_PAGE
            - 1
        )
        // PER_PAGE,
    )
    page = max(
        1,
        min(
            page,
            max_page,
        ),
    )
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
    buttons.append(
        nav
    )
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
        page = int(
            page_raw
        )
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
        (
            total
            + PER_PAGE
            - 1
        )
        // PER_PAGE,
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
            copied = await safe_copy_from_storage(
                call.bot,
                call.from_user.id,
                message_id,
            )
            if copied is None:
                continue
            sent += 1
        except Exception:
            logger.exception(
                (
                    "SEND PAGE ERROR "
                    "| message=%s"
                ),
                item.get("message_id"),
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
            copied = await safe_copy_from_storage(
                call.bot,
                call.from_user.id,
                message_id,
            )
            if copied is None:
                continue
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
                (
                    "SEND ALL ERROR "
                    "| message=%s"
                ),
                item.get("message_id"),
            )
    try:
        await progress.edit_text(
            (
                "✅ Semua file selesai\n\n"
                f"📦 Berhasil: "
                f"{sent}/{total}"
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
        page = int(
            page_raw
        )
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
        (
            total
            + PER_PAGE
            - 1
        )
        // PER_PAGE,
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
# NONE CALLBACK
# ============================================================
@router.callback_query(
    F.data == "none"
)
async def none_callback(
    call: CallbackQuery,
):
    await call.answer()
