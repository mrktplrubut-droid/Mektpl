import html
import json
import logging
import secrets
from typing import Any

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

MEDIA_TTL = 3600
PER_PAGE = 10

# Lama lock "Saya Sudah Bayar"
VERIFY_REQUEST_TTL = 300

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

# Telegram callback_data maksimal 64 bytes.
# Code panjang tidak boleh langsung dimasukkan ke callback.
CALLBACK_TOKEN_TTL = 900


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
    """
    Mendukung:

    ADMIN_IDS = [123, 456]
    ADMIN_IDS = (123, 456)
    ADMIN_IDS = {123, 456}
    ADMIN_IDS = "123,456"
    ADMIN_IDS = 123
    """

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

        result: set[int] = set()

        for value in values:
            value = str(value).strip()

            if not value:
                continue

            try:
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
    """
    Menyimpan data callback di Redis agar callback_data
    tidak melebihi batas 64 bytes Telegram.
    """

    token = secrets.token_urlsafe(10)

    key = f"cb:{prefix}:{token}"

    await safe_set(
        key,
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
            "GET CALLBACK TOKEN ERROR | prefix=%s",
            prefix,
        )
        return None


# ============================================================
# MEDIA PARSER
# ============================================================

def parse_media(media_data: Any) -> list[dict]:
    """
    Normalize media JSON/list menjadi list dictionary.
    """

    if isinstance(media_data, str):
        try:
            media_data = json.loads(media_data)
        except Exception:
            logger.exception("MEDIA JSON PARSE ERROR")
            return []

    if not isinstance(media_data, list):
        return []

    result: list[dict] = []

    for item in media_data:
        if not isinstance(item, dict):
            continue

        message_id = item.get("message_id")

        if message_id is None:
            continue

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
# DATABASE HELPERS
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
# UPGRADE NOTIFICATION
# ============================================================

async def send_upgrade_notif(
    bot,
    user_id: int,
    tier: str,
):
    try:
        tier = str(tier or "").lower()
        masked = mask_user_id(user_id)

        if tier == "vip":
            text = (
                "🌟 <b>VIP UPGRADE</b>\n\n"
                f"👤 User: <code>{masked}</code>\n"
                "📦 Paket: <b>VIP</b>"
            )

        elif tier == "vvip":
            text = (
                "👑 <b>VVIP UPGRADE</b>\n\n"
                f"👤 User: <code>{masked}</code>\n"
                "📦 Paket: <b>VVIP</b>"
            )

        else:
            return

        if NOTIF_CHANNEL_ID:
            await bot.send_message(
                NOTIF_CHANNEL_ID,
                text,
                parse_mode="HTML",
            )

    except Exception:
        logger.exception(
            "UPGRADE NOTIFICATION ERROR"
        )


# ============================================================
# MANUAL PAYMENT KEYBOARD
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
# PAYMENT ENTRY
# ============================================================

@router.callback_query(
    F.data.startswith("pay:")
)
async def choose_payment(
    call: CallbackQuery,
):
    try:
        code = call.data.split(":", 1)[1].strip()
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

    # Semua pembayaran diarahkan ke QR MANUAL.
    return await show_manual_payment(
        call,
        code,
        file,
    )


# ============================================================
# DIRECT MANUAL PAYMENT
# ============================================================

@router.callback_query(
    F.data.startswith("manual:")
)
async def manual_payment(
    call: CallbackQuery,
):
    try:
        code = call.data.split(":", 1)[1].strip()
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

    return await show_manual_payment(
        call,
        code,
        file,
    )


# ============================================================
# SHOW MANUAL PAYMENT
# ============================================================

async def show_manual_payment(
    call: CallbackQuery,
    code: str,
    file,
):
    user_id = int(call.from_user.id)
    code = str(code).strip()

    # --------------------------------------------------------
    # QR VALIDATION
    # --------------------------------------------------------

    if not MANUAL_QR_FILE_ID:
        logger.error(
            "MANUAL_QR_FILE_ID BELUM DIKONFIGURASI"
        )

        return await call.answer(
            "❌ QR Manual belum tersedia.",
            show_alert=True,
        )

    # --------------------------------------------------------
    # PRICE
    # --------------------------------------------------------

    price = safe_int(file.get("price"))

    if price <= 0:
        return await call.answer(
            "❌ Harga file tidak valid.",
            show_alert=True,
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

    # --------------------------------------------------------
    # CREATE PURCHASE
    # --------------------------------------------------------

    if not existing:
        payment_id = (
            f"MANUAL-{user_id}-"
            f"{secrets.token_hex(8)}"
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
                file.get("owner_id"),
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

    if not existing:
        return await call.answer(
            "❌ Transaksi gagal dibuat.",
            show_alert=True,
        )

    # --------------------------------------------------------
    # EXISTING QR
    # --------------------------------------------------------

    old_qr_message_id = existing.get(
        "qr_message_id"
    )

    old_qr_chat_id = existing.get(
        "qr_chat_id"
    )

    # Jangan membuat QR baru berkali-kali.
    if old_qr_message_id and old_qr_chat_id:
        try:
            await call.bot.send_message(
                user_id,
                (
                    "⏳ <b>Transaksi pembayaran masih aktif.</b>\n\n"
                    f"📦 <b>{clean_html(file.get('title'))}</b>\n"
                    f"💰 <b>{format_rupiah(price)}</b>\n\n"
                    "Silakan gunakan QR pembayaran yang "
                    "sudah dikirim sebelumnya.\n\n"
                    "Tekan <b>✅ Saya Sudah Bayar</b> "
                    "setelah pembayaran selesai."
                ),
                parse_mode="HTML",
            )

            return await call.answer(
                "⏳ Transaksi pembayaran masih aktif.",
                show_alert=True,
            )

        except Exception:
            logger.warning(
                "EXISTING QR CHECK FAILED | purchase=%s",
                existing.get("id"),
                exc_info=True,
            )

    # --------------------------------------------------------
    # CAPTION
    # --------------------------------------------------------

    title = clean_html(file.get("title"))
    safe_code = clean_html(code)

    caption = (
        "📷 <b>PEMBAYARAN MANUAL</b>\n\n"
        f"📄 File:\n"
        f"<b>{title}</b>\n\n"
        f"🔑 Code:\n"
        f"<code>{safe_code}</code>\n\n"
        f"💰 Harga:\n"
        f"<b>{format_rupiah(price)}</b>\n\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "📌 <b>Cara Pembayaran</b>\n\n"
        "1️⃣ Scan QR di atas\n"
        "2️⃣ Bayar sesuai nominal\n"
        "3️⃣ Pastikan pembayaran berhasil\n"
        "4️⃣ Tekan tombol <b>✅ Saya Sudah Bayar</b>\n\n"
        "⏳ Pembayaran akan diverifikasi admin.\n"
        "⚠️ Jangan melakukan pembayaran dua kali."
    )

    # --------------------------------------------------------
    # KEYBOARD
    # --------------------------------------------------------

    keyboard = await manual_payment_keyboard(
        code
    )

    # --------------------------------------------------------
    # SEND QR
    # --------------------------------------------------------

    try:
        msg = await call.message.answer_photo(
            photo=MANUAL_QR_FILE_ID,
            caption=caption,
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
        "📷 Silakan lakukan pembayaran."
    )


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
        token = call.data.split(":", 1)[1].strip()
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
            "❌ Tombol sudah expired.\n"
            "Silakan buka pembayaran kembali.",
            show_alert=True,
        )

    code = str(
        callback_data.get("code") or ""
    ).strip()

    user_id = int(call.from_user.id)

    if not code:
        return await call.answer(
            "❌ Code tidak valid.",
            show_alert=True,
        )

    # --------------------------------------------------------
    # FILE
    # --------------------------------------------------------

    file = await get_file_by_code(code)

    if not file:
        return await call.answer(
            "❌ File tidak ditemukan.",
            show_alert=True,
        )

    # --------------------------------------------------------
    # PURCHASE
    # --------------------------------------------------------

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

    if purchase_id <= 0:
        return await call.answer(
            "❌ ID transaksi tidak valid.",
            show_alert=True,
        )

    # --------------------------------------------------------
    # ANTI DUPLICATE ADMIN REQUEST
    # --------------------------------------------------------

    lock_key = (
        f"manualverify:{purchase_id}"
    )

    try:
        verification_lock = await safe_get(
            lock_key
        )

        if verification_lock:
            return await call.answer(
                "⏳ Permintaan verifikasi sudah dikirim.\n"
                "Mohon tunggu admin.",
                show_alert=True,
            )

        await safe_set(
            lock_key,
            {
                "purchase_id": purchase_id,
                "user_id": user_id,
            },
            ex=VERIFY_REQUEST_TTL,
        )

    except Exception:
        # Redis gagal bukan berarti payment gagal.
        logger.warning(
            "VERIFY REDIS LOCK ERROR",
            exc_info=True,
        )

    await call.answer(
        "⏳ Mengirim permintaan verifikasi..."
    )

    # --------------------------------------------------------
    # ADMIN MESSAGE
    # --------------------------------------------------------

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

    admin_ids = get_admin_ids()
    sent = 0

    for admin_id in admin_ids:
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
                "SEND MANUAL ADMIN ERROR | admin=%s",
                admin_id,
            )

    if sent == 0:
        # Lock dibuat singkat supaya user bisa mencoba kembali.
        try:
            await safe_set(
                lock_key,
                {
                    "failed": True,
                },
                ex=1,
            )
        except Exception:
            pass

        return await call.message.answer(
            "❌ Admin tidak dapat menerima permintaan."
        )

    try:
        await call.message.answer(
            "✅ Permintaan pembayaran sudah dikirim "
            "ke admin.\n\n"
            "⏳ Tunggu sampai pembayaran diverifikasi."
        )

    except Exception:
        logger.exception(
            "SEND USER PAYMENT WAITING MESSAGE ERROR"
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
        logger.error(
            "INVALID PURCHASE ID"
        )
        return False

    try:
        # ----------------------------------------------------
        # MEDIA
        # ----------------------------------------------------

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
            logger.warning(
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
                    buy_count =
                        COALESCE(buy_count, 0) + 1,
                    sold =
                        COALESCE(sold, 0) + 1
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
                    purchase_count =
                        LEAST(
                            3,
                            COALESCE(
                                purchase_count,
                                0
                            ) + 1
                        ),

                    completed =
                        (
                            LEAST(
                                3,
                                COALESCE(
                                    purchase_count,
                                    0
                                ) + 1
                            ) >= 3
                        ),

                    completed_at =
                        CASE
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
                "SELLER PROFIT ERROR | purchase=%s",
                purchase_id,
            )

        # ----------------------------------------------------
        # VIP / VVIP NOTIFICATION
        # ----------------------------------------------------

        try:
            code_lower = str(
                file.get("code") or ""
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
                        f"<b>{format_rupiah(purchase.get('paid_price'))}</b>"
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
                "DELETE PAYMENT QR FAILED | purchase=%s",
                purchase_id,
                exc_info=True,
            )

        # ----------------------------------------------------
        # SEND MEDIA MENU
        # ----------------------------------------------------

        total = len(media_list)

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
# APPROVE MANUAL
# ============================================================

@router.callback_query(
    F.data.startswith("approve:")
)
async def approve_manual(
    call: CallbackQuery,
    state: FSMContext,
):
    if not is_admin(call.from_user.id):
        return await call.answer(
            "❌ Kamu bukan admin.",
            show_alert=True,
        )

    await state.clear()

    try:
        purchase_id = int(
            call.data.split(":", 1)[1]
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
            "❌ Transaksi tidak ditemukan / sudah diproses.",
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
        "⏳ Memproses pembayaran..."
    )

    user_id = safe_int(
        purchase.get("user_id")
    )

    if user_id <= 0:
        return await call.answer(
            "❌ User transaksi tidak valid.",
            show_alert=True,
        )

    # --------------------------------------------------------
    # USER PROCESSING
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # FINISH
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # ADMIN MESSAGE
    # --------------------------------------------------------

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
                "📦 Media sudah dikirim ke user."
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
# REJECT MANUAL
# ============================================================

@router.callback_query(
    F.data.startswith("reject:")
)
async def reject_manual(
    call: CallbackQuery,
    state: FSMContext,
):
    if not is_admin(call.from_user.id):
        return await call.answer(
            "❌ Kamu bukan admin.",
            show_alert=True,
        )

    try:
        purchase_id = int(
            call.data.split(":", 1)[1]
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
            "❌ Transaksi tidak ditemukan / sudah diproses.",
            show_alert=True,
        )

    await state.set_state(
        RejectPaymentState.waiting_reason
    )

    await state.update_data(
        purchase_id=purchase_id,
        admin_id=int(call.from_user.id),
        admin_chat_id=int(call.message.chat.id),
        admin_message_id=int(call.message.message_id),
    )

    try:
        await call.message.reply(
            (
                "❌ <b>REJECT PEMBAYARAN</b>\n\n"
                f"🧾 ID Transaksi: "
                f"<code>{purchase_id}</code>\n"
                f"👤 User: "
                f"<code>{purchase['user_id']}</code>\n"
                f"📦 Code: "
                f"<code>{clean_html(purchase['file_code'])}</code>\n\n"
                "📝 <b>Silakan kirim alasan penolakan.</b>\n\n"
                "Contoh:\n"
                "• Bukti pembayaran tidak valid\n"
                "• Nominal pembayaran tidak sesuai\n"
                "• Pembayaran belum masuk\n\n"
                "Ketik <code>/cancelreject</code> "
                "untuk membatalkan."
            ),
            parse_mode="HTML",
        )

    except Exception:
        logger.exception(
            "REJECT PROMPT ERROR"
        )

        await state.clear()

        return await call.answer(
            "❌ Gagal meminta alasan.",
            show_alert=True,
        )

    await call.answer(
        "📝 Silakan kirim alasan penolakan."
    )


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
    if not is_admin(message.from_user.id):
        return

    data = await state.get_data()
    purchase_id = data.get("purchase_id")

    await state.clear()

    if purchase_id:
        text = (
            "↩️ <b>Reject dibatalkan.</b>\n\n"
            f"🧾 Transaksi <code>{purchase_id}</code> "
            "masih berstatus <b>pending</b>."
        )
    else:
        text = (
            "↩️ <b>Reject dibatalkan.</b>\n\n"
            "Silakan ulangi proses Reject."
        )

    await message.answer(
        text,
        parse_mode="HTML",
    )


# ============================================================
# RECEIVE REJECT REASON
# ============================================================

@router.message(
    RejectPaymentState.waiting_reason,
    F.text,
)
async def receive_reject_reason(
    message: Message,
    state: FSMContext,
):
    if not is_admin(message.from_user.id):
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
            "❌ Permintaan Reject ini milik admin lain."
        )

    if not purchase_id:
        await state.clear()

        return await message.answer(
            "❌ Data transaksi tidak ditemukan.\n"
            "Silakan ulangi proses Reject."
        )

    reason = str(
        message.text or ""
    ).strip()

    if not reason:
        return await message.answer(
            "❌ Alasan tidak boleh kosong.\n\n"
            "Silakan kirim alasan penolakan."
        )

    if len(reason) > 1000:
        return await message.answer(
            "❌ Alasan terlalu panjang.\n"
            "Maksimal 1000 karakter."
        )

    # --------------------------------------------------------
    # ATOMIC REJECT
    # --------------------------------------------------------

    rejected = await fetchrow(
        """
        UPDATE file_purchases
        SET
            status='rejected'
        WHERE id=$1
          AND status='pending'
        RETURNING *
        """,
        purchase_id,
    )

    if not rejected:
        await state.clear()

        return await message.answer(
            "❌ Transaksi sudah diproses oleh admin lain."
        )

    user_id = safe_int(
        rejected.get("user_id")
    )

    code = str(
        rejected.get("file_code") or ""
    )

    safe_reason = clean_html(reason)

    # --------------------------------------------------------
    # NOTIFY USER
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
                "💡 Silakan lakukan pembayaran ulang "
                "jika diperlukan."
            ),
            parse_mode="HTML",
        )

        user_notified = True

    except Exception:
        logger.exception(
            "SEND REJECT REASON TO USER ERROR | "
            "purchase=%s | user=%s",
            purchase_id,
            user_id,
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
            "DELETE REJECT QR FAILED | purchase=%s",
            purchase_id,
            exc_info=True,
        )

    # --------------------------------------------------------
    # UPDATE ORIGINAL ADMIN MESSAGE
    # --------------------------------------------------------

    original_chat_id = data.get(
        "admin_chat_id"
    )

    original_message_id = data.get(
        "admin_message_id"
    )

    if (
        original_chat_id
        and original_message_id
    ):
        try:
            await message.bot.edit_message_text(
                chat_id=int(original_chat_id),
                message_id=int(original_message_id),
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
                "EDIT ORIGINAL REJECT MESSAGE FAILED",
                exc_info=True,
            )

    # --------------------------------------------------------
    # ADMIN RESULT
    # --------------------------------------------------------

    try:
        await message.answer(
            (
                "❌ <b>PEMBAYARAN DITOLAK</b>\n\n"
                f"🧾 ID: <code>{purchase_id}</code>\n"
                f"👤 User: <code>{user_id}</code>\n"
                f"📦 Code: <code>{clean_html(code)}</code>\n\n"
                "📝 <b>Alasan:</b>\n"
                f"{safe_reason}\n\n"
                f"👤 User diberi notifikasi: "
                f"{'✅ Ya' if user_notified else '❌ Gagal'}\n"
                f"🗑 QR dihapus: "
                f"{'✅ Ya' if qr_deleted else '⚠️ Tidak ditemukan'}"
            ),
            parse_mode="HTML",
        )

    except Exception:
        logger.exception(
            "SEND ADMIN REJECT RESULT ERROR"
        )

    await state.clear()


# ============================================================
# CLOSE PAYMENT
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

    if session_user_id is None:
        logger.warning(
            "MEDIA SESSION WITHOUT USER | media=%s",
            media_id,
        )

        await call.answer(
            "❌ Session media tidak valid.",
            show_alert=True,
        )

        return None

    try:
        authorized = (
            int(session_user_id)
            == int(call.from_user.id)
        )
    except Exception:
        authorized = False

    if not authorized:
        logger.warning(
            "UNAUTHORIZED MEDIA ACCESS | media=%s | user=%s",
            media_id,
            call.from_user.id,
        )

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

    except (ValueError, TypeError, AttributeError):
        return await call.answer(
            "❌ Data halaman tidak valid.",
            show_alert=True,
        )

    if page < 1:
        return await call.answer(
            "❌ Halaman tidak valid.",
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

    if not isinstance(media_list, list):
        return await call.answer(
            "❌ Data media tidak valid.",
            show_alert=True,
        )

    total = len(media_list)

    if total <= 0:
        return await call.answer(
            "❌ Media kosong.",
            show_alert=True,
        )

    max_page = max(
        1,
        (total + PER_PAGE - 1) // PER_PAGE,
    )

    if page > max_page:
        return await call.answer(
            "❌ Halaman tidak ditemukan.",
            show_alert=True,
        )

    start = (page - 1) * PER_PAGE
    end = start + PER_PAGE

    items = media_list[start:end]

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
                "SEND PAGE ERROR | media=%s | item=%s",
                media_id,
                item,
            )

    try:
        await call.message.answer(
            (
                f"✅ Halaman {page} selesai\n\n"
                f"📦 Terkirim: "
                f"{sent}/{len(items)} file"
            )
        )

    except Exception:
        logger.exception(
            "SEND PAGE RESULT ERROR"
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

    except (ValueError, TypeError, AttributeError):
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

    if (
        not isinstance(media_list, list)
        or not media_list
    ):
        return await call.answer(
            "❌ Media kosong.",
            show_alert=True,
        )

    await call.answer(
        "📦 Mengirim semua file..."
    )

    total = len(media_list)

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

            if index % 5 == 0 or index == total:
                try:
                    await progress.edit_text(
                        f"⏳ Mengirim {index}/{total}"
                    )
                except Exception:
                    pass

        except Exception:
            logger.exception(
                "SEND ALL ERROR | media=%s | item=%s",
                media_id,
                item,
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

    except (ValueError, TypeError, AttributeError):
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

    if (
        not isinstance(media_list, list)
        or not media_list
    ):
        return await call.answer(
            "❌ Media tidak ditemukan.",
            show_alert=True,
        )

    total = len(media_list)

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
# NONE CALLBACK
# ============================================================

@router.callback_query(
    F.data == "none"
)
async def none_callback(
    call: CallbackQuery,
):
    await call.answer()
