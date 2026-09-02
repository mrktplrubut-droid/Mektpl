import html
import json
import logging
import secrets
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
# FSM - ADMIN REJECT REASON
# ============================================================
class RejectPaymentState(StatesGroup):
    waiting_reason = State()
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
        return int(user_id) in {
            int(x) for x in ADMIN_IDS
        }
    except Exception:
        return False
def clean_html(value) -> str:
    """
    Mencegah input user/admin merusak HTML Telegram.
    """
    return html.escape(str(value or ""))
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
        logger.exception(
            "UPGRADE NOTIF ERROR"
        )
# ============================================================
# MANUAL PAYMENT KEYBOARD
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
        (total + PER_PAGE - 1) // PER_PAGE,
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
async def choose_payment(call: CallbackQuery):
    code = call.data.split(
        ":",
        1,
    )[1].strip()
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
    try:
        price = int(file["price"] or 0)
    except Exception:
        price = 0
    if price <= 0:
        return await call.answer(
            "❌ Harga file tidak valid.",
            show_alert=True,
        )
    # Semua pembayaran menggunakan QR Manual
    return await show_manual_payment(
        call,
        code,
        file,
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
    # VALIDASI QR
    # ========================================================
    if not MANUAL_QR_FILE_ID:
        logger.error(
            "MANUAL_QR_FILE_ID belum dikonfigurasi"
        )
        return await call.answer(
            "❌ QR Manual belum tersedia.",
            show_alert=True,
        )
    # ========================================================
    # CEK TRANSAKSI PENDING
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
        f"<b>{clean_html(file['title'])}</b>\n\n"
        f"🔑 Code:\n"
        f"<code>{clean_html(code)}</code>\n\n"
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
# ============================================================
# DIRECT MANUAL BUTTON
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
    )[1].strip()
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
async def manual_check(
    call: CallbackQuery,
):
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
        f"📄 File: <b>{clean_html(file['title'])}</b>\n"
        f"🔑 Code: <code>{clean_html(code)}</code>\n"
        f"💰 Harga: "
        f"<b>{format_rupiah(purchase['paid_price'])}</b>\n"
        f"🧾 ID: <code>{purchase['id']}</code>\n"
        f"💳 Payment: "
        f"<code>{clean_html(purchase['payment_id'])}</code>"
    )
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Approve",
                    callback_data=f"approve:{purchase['id']}",
                ),
                InlineKeyboardButton(
                    text="❌ Reject",
                    callback_data=f"reject:{purchase['id']}",
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
                    file.get(
                        "share_media",
                        False,
                    )
                ),
                "invoice": invoice,
                "purchase_id": purchase_id,
            },
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
                RETURNING
                    user_id,
                    completed
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
                                f"Code <code>{clean_html(file['code'])}</code>\n"
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
                    f"📄 Judul: "
                    f"<b>{clean_html(file['title'])}</b>\n"
                    f"📁 Code: "
                    f"<code>{clean_html(file['code'])}</code>\n"
                    f"👤 User: "
                    f"<code>{masked}</code>"
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
            "purchase=%s | "
            "user=%s | "
            "code=%s",
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
    # Bersihkan state reject apabila ada
    await state.clear()
    try:
        purchase_id = int(
            call.data.split(
                ":",
                1,
            )[1]
        )
    except ValueError:
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
    # USER PROCESSING
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
                f"👤 User: "
                f"<code>{user_id}</code>\n"
                f"📦 File: "
                f"<b>{clean_html(file['title'])}</b>\n"
                f"🔑 Code: "
                f"<code>{clean_html(file['code'])}</code>\n"
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
#
# ALUR BARU:
#
# Admin klik Reject
#        ↓
# Bot meminta alasan
#        ↓
# Admin mengetik alasan
#        ↓
# Transaksi menjadi rejected
#        ↓
# QR dihapus
#        ↓
# User menerima alasan penolakan
#
# ============================================================
@router.callback_query(
    F.data.startswith("reject:")
)
async def reject_manual(
    call: CallbackQuery,
    state: FSMContext,
):
    # ========================================================
    # ADMIN CHECK
    # ========================================================
    if not is_admin(
        call.from_user.id
    ):
        return await call.answer(
            "❌ Kamu bukan admin.",
            show_alert=True,
        )
    # ========================================================
    # PARSE ID
    # ========================================================
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
    # ========================================================
    # VALIDASI TRANSAKSI
    # ========================================================
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
    # ========================================================
    # SIMPAN DATA KE FSM
    # ========================================================
    await state.set_state(
        RejectPaymentState.waiting_reason
    )
    await state.update_data(
        purchase_id=purchase_id
    )
    # ========================================================
    # ADMIN PROMPT
    # ========================================================
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
# ADMIN SEND REJECT REASON
# ============================================================
@router.message(
    RejectPaymentState.waiting_reason,
    F.text,
)
async def receive_reject_reason(
    message: Message,
    state: FSMContext,
):
    # ========================================================
    # ADMIN CHECK
    # ========================================================
    if not is_admin(
        message.from_user.id
    ):
        return await message.answer(
            "❌ Kamu bukan admin."
        )
    # ========================================================
    # AMBIL STATE
    # ========================================================
    data = await state.get_data()
    purchase_id = data.get(
        "purchase_id"
    )
    if not purchase_id:
        await state.clear()
        return await message.answer(
            "❌ Data transaksi tidak ditemukan.\n"
            "Silakan ulangi proses Reject."
        )
    # ========================================================
    # VALIDASI ALASAN
    # ========================================================
    reason = str(
        message.text or ""
    ).strip()
    if not reason:
        return await message.answer(
            "❌ Alasan tidak boleh kosong.\n\n"
            "Silakan kirim alasan penolakan."
        )
    # Batasi panjang agar pesan tetap aman
    if len(reason) > 1000:
        return await message.answer(
            "❌ Alasan terlalu panjang.\n"
            "Maksimal 1000 karakter."
        )
    # ========================================================
    # ATOMIC REJECT
    # ========================================================
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
    user_id = rejected["user_id"]
    code = rejected["file_code"]
    # ========================================================
    # ESCAPE REASON
    # ========================================================
    safe_reason = clean_html(
        reason
    )
    # ========================================================
    # NOTIFY USER
    # ========================================================
    user_notified = False
    try:
        await message.bot.send_message(
            user_id,
            (
                "❌ <b>Pembayaran Ditolak</b>\n\n"
                f"📦 Code: "
                f"<code>{clean_html(code)}</code>\n\n"
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
    # ========================================================
    # DELETE PAYMENT QR
    # ========================================================
    qr_deleted = False
    try:
        qr_message_id = rejected.get(
            "qr_message_id"
        )
        qr_chat_id = rejected.get(
            "qr_chat_id"
        )
        if (
            qr_message_id
            and qr_chat_id
        ):
            await message.bot.delete_message(
                chat_id=qr_chat_id,
                message_id=qr_message_id,
            )
            qr_deleted = True
    except Exception:
        logger.warning(
            "DELETE REJECT QR FAILED | "
            "purchase=%s",
            purchase_id,
            exc_info=True,
        )
    # ========================================================
    # UPDATE ADMIN MESSAGE
    # ========================================================
    # Cari pesan admin yang berisi tombol Reject.
    #
    # Karena message ID asli tersimpan di callback query,
    # pesan tersebut tidak tersedia lagi di handler message.
    #
    # Sebagai gantinya, kita kirim hasil final ke admin.
    # ========================================================
    try:
        await message.answer(
            (
                "❌ <b>PEMBAYARAN DITOLAK</b>\n\n"
                f"🧾 ID: "
                f"<code>{purchase_id}</code>\n"
                f"👤 User: "
                f"<code>{user_id}</code>\n"
                f"📦 Code: "
                f"<code>{clean_html(code)}</code>\n\n"
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
    # ========================================================
    # CLEAR FSM
    # ========================================================
    await state.clear()
# ============================================================
# CANCEL REJECT REASON
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
            + (
                f"🧾 Transaksi <code>{purchase_id}</code> "
                "masih berstatus <b>pending</b>."
                if purchase_id
                else "Silakan ulangi proses pembayaran."
            )
        ),
        parse_mode="HTML",
    )
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
async def send_page_media(
    call: CallbackQuery,
):
    try:
        _, media_id, page_raw = (
            call.data.split(":")
        )
        page = int(page_raw)
    except (
        ValueError,
        AttributeError,
    ):
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
    start = (
        page - 1
    ) * PER_PAGE
    end = start + PER_PAGE
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
# SEND ALL
# ============================================================
@router.callback_query(
    F.data.startswith("sa:")
)
async def send_all_media(
    call: CallbackQuery,
):
    try:
        _, media_id = (
            call.data.split(":")
        )
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
async def media_page(
    call: CallbackQuery,
):
    try:
        _, media_id, page_raw = (
            call.data.split(":")
        )
        page = int(page_raw)
    except (
        ValueError,
        AttributeError,
    ):
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
        ) // PER_PAGE,
    )
    if (
        page < 1
        or page > max_page
    ):
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
async def none_callback(
    call: CallbackQuery,
):
    await call.answer()
