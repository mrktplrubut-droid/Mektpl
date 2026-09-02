import json
import logging
import secrets
from aiogram import Router, F
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from database import fetchrow, fetch, execute
from utils.redis_client import (
    safe_set,
    safe_get,
    safe_delete,
)
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
CHECK_LOCK = set()
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
# HELPERS
# ============================================================
def mask_user_id(user_id: int) -> str:
    uid = str(user_id)
    if len(uid) <= 4:
        return "****"
    return uid[:2] + "****" + uid[-2:]
def format_rupiah(amount) -> str:
    try:
        return f"Rp {int(amount):,}".replace(",", ".")
    except Exception:
        return f"Rp {amount}"
def normalize_status(value) -> str:
    return str(value or "").strip().lower()
def is_admin(user_id: int) -> bool:
    try:
        return int(user_id) in {int(x) for x in ADMIN_IDS}
    except Exception:
        return False
# ============================================================
# UPGRADE NOTIFICATION
# ============================================================
async def send_upgrade_notif(bot, user_id, tier):
    try:
        tier = str(tier or "").lower()
        masked = mask_user_id(user_id)
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
        logger.exception("UPGRADE NOTIF ERROR")
# ============================================================
# PAYMENT KEYBOARD
# ============================================================
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
# ============================================================
# MEDIA KEYBOARD
# ============================================================
def media_keyboard(media_id, page, total):
    max_page = max(
        1,
        (total + PER_PAGE - 1) // PER_PAGE
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
@router.callback_query(F.data.startswith("pay:"))
async def choose_payment(call: CallbackQuery):
    """
    Semua pembelian file sekarang menggunakan QR MANUAL.
    QR otomatis sementara dinonaktifkan.
    """
    code = call.data.split(":", 1)[1].strip()
    if not code:
        return await call.answer(
            "❌ Code tidak valid.",
            show_alert=True,
        )
    file = await fetchrow(
        """
        SELECT *
        FROM files
        WHERE code=$1
        LIMIT 1
        """,
        code,
    )
    if not file:
        return await call.answer(
            "❌ File tidak ditemukan.",
            show_alert=True,
        )
    price = int(file["price"] or 0)
    if price <= 0:
        return await call.answer(
            "❌ Harga file tidak valid.",
            show_alert=True,
        )
    # Langsung ke QR Manual
    return await show_manual_payment(
        call,
        code,
        file,
    )
# ============================================================
# OLD AUTOMATIC PAYMENT BLOCK
# ============================================================
@router.callback_query(
    F.data.startswith("auto:")
)
async def disabled_auto_payment(call: CallbackQuery):
    """
    QR Otomatis 1 sengaja dinonaktifkan sementara.
    """
    await call.answer(
        "⚠️ QR Otomatis sedang dalam perbaikan pusat.\n"
        "Silakan gunakan QR Manual.",
        show_alert=True,
    )
@router.callback_query(
    F.data.startswith("dompetx:")
)
async def disabled_dompetx_payment(call: CallbackQuery):
    """
    QR Otomatis 2 sengaja dinonaktifkan sementara.
    """
    await call.answer(
        "⚠️ QR Otomatis sedang dalam perbaikan pusat.\n"
        "Silakan gunakan QR Manual.",
        show_alert=True,
    )
# ============================================================
# MANUAL PAYMENT
# ============================================================
async def show_manual_payment(
    call: CallbackQuery,
    code: str,
    file,
):
    user_id = call.from_user.id
    # ========================================================
    # CEK PENDING EXISTING
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
            f"MANUAL-{user_id}-"
            f"{code}-"
            f"{secrets.token_hex(6)}"
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
                int(file["price"] or 0),
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
    price = int(file["price"] or 0)
    caption = (
        "📷 <b>PEMBAYARAN MANUAL</b>\n\n"
        f"📄 File:\n"
        f"<b>{file['title']}</b>\n\n"
        f"🔑 Code:\n"
        f"<code>{code}</code>\n\n"
        f"💰 Harga:\n"
        f"<b>{format_rupiah(price)}</b>\n\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "📌 <b>Cara Pembayaran</b>\n\n"
        "1️⃣ Scan QR di atas\n"
        "2️⃣ Bayar sesuai nominal\n"
        "3️⃣ Pastikan pembayaran berhasil\n"
        "4️⃣ Tekan tombol "
        "<b>✅ Saya Sudah Bayar</b>\n\n"
        "⏳ Pembayaran akan diverifikasi admin."
    )
    # ========================================================
    # SEND QR
    # ========================================================
    try:
        msg = await call.message.answer_photo(
            MANUAL_QR_FILE_ID,
            caption=caption,
            parse_mode="HTML",
            reply_markup=manual_payment_keyboard(code),
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
        "📷 Silakan lakukan pembayaran."
    )
@router.callback_query(
    F.data.startswith("manual:")
)
async def manual_payment(call: CallbackQuery):
    code = call.data.split(
        ":",
        1,
    )[1].strip()
    file = await fetchrow(
        """
        SELECT *
        FROM files
        WHERE code=$1
        LIMIT 1
        """,
        code,
    )
    if not file:
        return await call.answer(
            "❌ File tidak ditemukan.",
            show_alert=True,
        )
    return await show_manual_payment(
        call,
        code,
        file,
    )
# ============================================================
# MANUAL PAYMENT CHECK
# ============================================================
@router.callback_query(
    F.data.startswith("manualcheck:")
)
async def manual_check(call: CallbackQuery):
    code = call.data.split(
        ":",
        1,
    )[1].strip()
    user_id = call.from_user.id
    file = await fetchrow(
        """
        SELECT *
        FROM files
        WHERE code=$1
        LIMIT 1
        """,
        code,
    )
    if not file:
        return await call.answer(
            "❌ File tidak ditemukan.",
            show_alert=True,
        )
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
    # ADMIN REQUEST
    # ========================================================
    text = (
        "📥 <b>MANUAL PAYMENT CHECK</b>\n\n"
        f"👤 User: <code>{user_id}</code>\n"
        f"📄 File: <b>{file['title']}</b>\n"
        f"🔑 Code: <code>{code}</code>\n"
        f"💰 Harga: "
        f"<b>{format_rupiah(purchase['paid_price'])}</b>\n"
        f"🧾 ID: <code>{purchase['id']}</code>\n"
        f"💳 Payment: "
        f"<code>{purchase['payment_id']}</code>"
    )
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Approve",
                    callback_data=(
                        f"approve:{purchase['id']}"
                    ),
                ),
                InlineKeyboardButton(
                    text="❌ Reject",
                    callback_data=(
                        f"reject:{purchase['id']}"
                    ),
                ),
            ]
        ]
    )
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
    await call.answer(
        "✅ Permintaan verifikasi dikirim ke admin."
    )
    try:
        await call.message.answer(
            "✅ Permintaan pembayaran sudah dikirim ke admin.\n"
            "⏳ Tunggu sampai pembayaran diverifikasi."
        )
    except Exception:
        pass
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
    try:
        purchase_id = purchase["id"]
        # ====================================================
        # PARSE MEDIA
        # ====================================================
        media_data = file.get("media")
        if isinstance(media_data, str):
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
            media_list = media_data or []
        media_list = [
            item
            for item in media_list
            if isinstance(item, dict)
            and item.get("message_id")
        ]
        if not media_list:
            await message.answer(
                "❌ Media file kosong."
            )
            return False
        # ====================================================
        # ATOMIC PAID
        # ====================================================
        updated = await fetchrow(
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
        if not updated:
            logger.warning(
                "PAYMENT ALREADY PROCESSED | purchase=%s",
                purchase_id,
            )
            return False
        purchase = updated
        # ====================================================
        # MEDIA SESSION
        # ====================================================
        media_id = secrets.token_hex(16)
        await safe_set(
            f"paidmedia:{media_id}",
            {
                "user_id": int(
                    purchase["user_id"]
                ),
                "media": media_list,
                "share_media": bool(
                    file.get("share_media", False)
                ),
                "invoice": invoice,
                "purchase_id": purchase_id,
            },
            ex=MEDIA_TTL,
        )
        # Simpan session supaya bisa dihapus saat cancel/cleanup
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
                    buy_count =
                        COALESCE(buy_count, 0) + 1,
                    sold =
                        COALESCE(sold, 0) + 1,
                    free_progress =
                        LEAST(
                            3,
                            COALESCE(
                                free_progress,
                                0
                            ) + 1
                        )
                WHERE code=$1
                """,
                file["code"],
            )
        except Exception:
            logger.exception(
                "BUY COUNT UPDATE ERROR"
            )
        # ====================================================
        # FREE PROGRESS
        # ====================================================
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
                  AND completed=FALSE
                RETURNING user_id, completed
                """,
                file["code"],
            )
            for row in completed_rows:
                if row["completed"]:
                    try:
                        await bot.send_message(
                            row["user_id"],
                            (
                                "🎉 <b>Progress Code Free 3/3!</b>\n\n"
                                f"Code <code>{file['code']}</code>\n"
                                "sudah bisa kamu buka gratis "
                                "karena telah mencapai 3 pembelian berhasil."
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
                "SELLER PROFIT ERROR | purchase=%s",
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
            "PAYMENT FINISHED | "
            "purchase=%s | user=%s | code=%s",
            purchase_id,
            purchase["user_id"],
            file["code"],
        )
        return True
    except Exception:
        logger.exception(
            "FINISH PAYMENT ERROR"
        )
        return False
# ============================================================
# APPROVE MANUAL
# ============================================================
@router.callback_query(
    F.data.startswith("approve:")
)
async def approve_manual(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        return await call.answer(
            "❌ Kamu bukan admin.",
            show_alert=True,
        )
    try:
        purchase_id = int(
            call.data.split(":", 1)[1]
        )
    except ValueError:
        return await call.answer(
            "❌ ID transaksi tidak valid.",
            show_alert=True,
        )
    # Ambil pending saja
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
    file = await fetchrow(
        """
        SELECT *
        FROM files
        WHERE code=$1
        LIMIT 1
        """,
        purchase["file_code"],
    )
    if not file:
        return await call.answer(
            "❌ File tidak ditemukan.",
            show_alert=True,
        )
    await call.answer(
        "⏳ Memproses pembayaran..."
    )
    user_id = purchase["user_id"]
    # ========================================================
    # SEND USER MESSAGE
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
            "❌ Pembayaran sudah diproses / gagal.",
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
                f"🔑 Code: <code>{file['code']}</code>\n"
                f"💰 Harga: "
                f"<b>{format_rupiah(purchase['paid_price'])}</b>"
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
async def reject_manual(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        return await call.answer(
            "❌ Kamu bukan admin.",
            show_alert=True,
        )
    try:
        purchase_id = int(
            call.data.split(":", 1)[1]
        )
    except ValueError:
        return await call.answer(
            "❌ ID transaksi tidak valid.",
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
                f"📦 Code: <code>{code}</code>\n\n"
                "Silakan lakukan pembayaran ulang."
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
        logger.warning(
            "DELETE REJECT QR FAILED",
            exc_info=True,
        )
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
# CLOSE
# ============================================================
@router.callback_query(
    F.data == "close"
)
async def close_payment(call: CallbackQuery):
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
    """
    Memastikan session media benar-benar milik
    user yang menekan tombol.
    """
    data = await safe_get(
        f"paidmedia:{media_id}"
    )
    if not data:
        await call.answer(
            "❌ Session media sudah expired.",
            show_alert=True,
        )
        return None
    session_user_id = data.get(
        "user_id"
    )
    if (
        session_user_id is None
        or int(session_user_id)
        != int(call.from_user.id)
    ):
        logger.warning(
            "UNAUTHORIZED MEDIA ACCESS | "
            "media=%s | user=%s",
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
async def send_page_media(call: CallbackQuery):
    try:
        _, media_id, page_raw = call.data.split(":")
        page = int(page_raw)
    except (ValueError, AttributeError):
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
        []
    )
    start = (
        page - 1
    ) * PER_PAGE
    end = start + PER_PAGE
    items = media_list[start:end]
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
# SEND ALL
# ============================================================
@router.callback_query(
    F.data.startswith("sa:")
)
async def send_all_media(call: CallbackQuery):
    try:
        _, media_id = call.data.split(":")
    except ValueError:
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
# MEDIA NAVIGATION
# ============================================================
@router.callback_query(
    F.data.startswith("mp:")
)
async def media_page(call: CallbackQuery):
    try:
        _, media_id, page_raw = call.data.split(":")
        page = int(page_raw)
    except (ValueError, AttributeError):
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
        []
    )
    if not media_list:
        return await call.answer(
            "❌ Media tidak ditemukan.",
            show_alert=True,
        )
    total = len(media_list)
    max_page = max(
        1,
        (total + PER_PAGE - 1) // PER_PAGE
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
        logger.exception(
            "MEDIA PAGINATION ERROR"
        )
    await call.answer()
# ============================================================
# NONE
# ============================================================
@router.callback_query(
    F.data == "none"
)
async def none_callback(call: CallbackQuery):
    await call.answer()
