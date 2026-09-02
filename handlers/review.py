from html import escape
from urllib.parse import quote
from aiogram import Router, F
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import (
    CallbackQuery,
    Message,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from database import get_pool
router = Router()
# ============================================================================
# LANGUAGE
# ============================================================================
async def lang_of(user_id: int) -> str:
    """
    Get user's language from database.
    Returns:
        "id" -> Indonesian
        "en" -> English
    Safe fallback:
        Indonesian
    """
    try:
        pool = await get_pool()
        language = await pool.fetchval(
            """
            SELECT language
            FROM users
            WHERE id = $1
            LIMIT 1
            """,
            user_id,
        )
        language = str(language or "").lower().strip()
        if language in {"en", "english"}:
            return "en"
        return "id"
    except Exception:
        # Never let language lookup break the actual handler.
        return "id"
# ============================================================================
# SAFE TELEGRAM EDIT
# ============================================================================
async def safe_edit_message(
    call: CallbackQuery,
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
):
    """
    Edit callback message safely.
    Telegram raises:
    BadRequest: message is not modified
    when the exact same text/markup is submitted.
    """
    try:
        return await call.message.edit_text(
            text,
            parse_mode="HTML",
            reply_markup=reply_markup,
        )
    except TelegramBadRequest as e:
        error_text = str(e).lower()
        if "message is not modified" in error_text:
            return None
        raise
# ============================================================================
# REVIEW STATE
# ============================================================================
class ReviewState(StatesGroup):
    waiting_text = State()
# ============================================================================
# DATABASE
# ============================================================================
async def ensure_review_table(pool):
    """
    Create review table if it does not exist.
    This is kept as a compatibility fallback.
    Ideally the table should be created through the main SQL migration.
    """
    await pool.execute(
        """
        CREATE TABLE IF NOT EXISTS file_reviews (
            id BIGSERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL,
            file_code TEXT NOT NULL,
            review TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW(),
            UNIQUE(user_id, file_code)
        )
        """
    )
# ============================================================================
# START REVIEW
# ============================================================================
@router.callback_query(F.data.startswith("review:"))
async def review_start(call: CallbackQuery, state: FSMContext):
    code = call.data.split(":", 1)[1].strip()
    if not code:
        return await call.answer(
            "❌ Code tidak valid.",
            show_alert=True,
        )
    lang = await lang_of(call.from_user.id)
    pool = await get_pool()
    exists = await pool.fetchval(
        """
        SELECT 1
        FROM files
        WHERE code = $1
        LIMIT 1
        """,
        code,
    )
    if not exists:
        return await call.answer(
            "❌ Code tidak ditemukan."
            if lang == "id"
            else "❌ Code not found.",
            show_alert=True,
        )
    await state.update_data(review_code=code)
    await state.set_state(ReviewState.waiting_text)
    if lang == "en":
        text = (
            "💬 <b>WRITE A REVIEW</b>\n\n"
            "Share your experience with this code/media.\n"
            "A clear review helps other buyers make better decisions.\n\n"
            "Type <b>cancel</b> to cancel."
        )
        cancel_text = "⬅️ Cancel"
    else:
        text = (
            "💬 <b>TULIS REVIEW</b>\n\n"
            "Tulis pengalaman kamu tentang code/media ini.\n"
            "Review yang jelas membantu pembeli lain mengambil keputusan.\n\n"
            "Ketik <b>batal</b> untuk membatalkan."
        )
        cancel_text = "⬅️ Batal"
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=cancel_text,
                    callback_data=f"market:{code}",
                )
            ]
        ]
    )
    try:
        await safe_edit_message(
            call,
            text,
            keyboard,
        )
    finally:
        await call.answer()
# ============================================================================
# SAVE REVIEW
# ============================================================================
@router.message(ReviewState.waiting_text)
async def review_save(message: Message, state: FSMContext):
    lang = await lang_of(message.from_user.id)
    text = (message.text or "").strip()
    data = await state.get_data()
    code = str(data.get("review_code") or "").strip()
    # ------------------------------------------------------------------------
    # Session expired
    # ------------------------------------------------------------------------
    if not code:
        await state.clear()
        return await message.answer(
            "❌ Sesi review berakhir. Silakan buka detail code lagi."
            if lang == "id"
            else
            "❌ Your review session has expired. Please open the code details again."
        )
    # ------------------------------------------------------------------------
    # Cancel
    # ------------------------------------------------------------------------
    if text.lower() in {
        "batal",
        "cancel",
        "/cancel",
    }:
        await state.clear()
        return await message.answer(
            "↩️ Review dibatalkan."
            if lang == "id"
            else
            "↩️ Review cancelled."
        )
    # ------------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------------
    if len(text) < 3:
        return await message.answer(
            "⚠️ Review terlalu singkat. Tulis minimal 3 karakter."
            if lang == "id"
            else
            "⚠️ Your review is too short. Please write at least 3 characters."
        )
    # Limit review length.
    text = text[:1000]
    pool = await get_pool()
    # ------------------------------------------------------------------------
    # Make sure table exists
    # ------------------------------------------------------------------------
    await ensure_review_table(pool)
    # ------------------------------------------------------------------------
    # Make sure code still exists
    # ------------------------------------------------------------------------
    file_exists = await pool.fetchval(
        """
        SELECT 1
        FROM files
        WHERE code = $1
        LIMIT 1
        """,
        code,
    )
    if not file_exists:
        await state.clear()
        return await message.answer(
            "❌ Code tidak ditemukan."
            if lang == "id"
            else
            "❌ Code not found."
        )
    # ------------------------------------------------------------------------
    # Save / update review
    # ------------------------------------------------------------------------
    await pool.execute(
        """
        INSERT INTO file_reviews (
            user_id,
            file_code,
            review
        )
        VALUES ($1, $2, $3)
        ON CONFLICT (user_id, file_code)
        DO UPDATE SET
            review = EXCLUDED.review,
            updated_at = NOW()
        """,
        message.from_user.id,
        code,
        text,
    )
    # ------------------------------------------------------------------------
    # Update review count
    # ------------------------------------------------------------------------
    await pool.execute(
        """
        UPDATE files
        SET review_count = (
            SELECT COUNT(*)
            FROM file_reviews
            WHERE file_code = $1
        )
        WHERE code = $1
        """,
        code,
    )
    await state.clear()
    return await message.answer(
        "✅ Review berhasil disimpan. Terima kasih sudah membantu marketplace!"
        if lang == "id"
        else
        "✅ Your review has been saved. Thank you for helping the marketplace!"
    )
# ============================================================================
# REVIEW LIST
# ============================================================================
@router.callback_query(F.data.startswith("reviews:"))
async def review_list(call: CallbackQuery):
    code = call.data.split(":", 1)[1].strip()
    lang = await lang_of(call.from_user.id)
    pool = await get_pool()
    # Make sure table exists.
    await ensure_review_table(pool)
    rows = await pool.fetch(
        """
        SELECT
            user_id,
            review,
            created_at
        FROM file_reviews
        WHERE file_code = $1
        ORDER BY created_at DESC
        LIMIT 10
        """,
        code,
    )
    if lang == "en":
        title = "💬 <b>LATEST REVIEWS</b>"
        empty = "No reviews for this code yet."
        write_review = "💬 Write Review"
        back = "⬅️ Back"
    else:
        title = "💬 <b>REVIEW TERBARU</b>"
        empty = "Belum ada review untuk code ini."
        write_review = "💬 Tulis Review"
        back = "⬅️ Kembali"
    # ------------------------------------------------------------------------
    # Empty
    # ------------------------------------------------------------------------
    if not rows:
        text = (
            f"{title}\n\n"
            f"📭 {empty}"
        )
    # ------------------------------------------------------------------------
    # Reviews
    # ------------------------------------------------------------------------
    else:
        parts = [
            title,
            "━━━━━━━━━━━━━━━━━━",
        ]
        for i, row in enumerate(rows, 1):
            user_id = escape(str(row["user_id"]))
            review = escape(str(row["review"]))
            parts.append(
                f"\n"
                f"<b>{i}.</b> User <code>{user_id}</code>\n"
                f"{review}"
            )
        text = "\n".join(parts)
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=write_review,
                    callback_data=f"review:{code}",
                )
            ],
            [
                InlineKeyboardButton(
                    text=back,
                    callback_data=f"market:{code}",
                )
            ],
        ]
    )
    try:
        await safe_edit_message(
            call,
            text,
            keyboard,
        )
    finally:
        await call.answer()
# ============================================================================
# SHARE CODE
# ============================================================================
@router.callback_query(F.data.startswith("share:"))
async def share_code(call: CallbackQuery):
    code = call.data.split(":", 1)[1].strip()
    lang = await lang_of(call.from_user.id)
    pool = await get_pool()
    row = await pool.fetchrow(
        """
        SELECT title
        FROM files
        WHERE code = $1
        LIMIT 1
        """,
        code,
    )
    if not row:
        return await call.answer(
            "❌ Code tidak ditemukan."
            if lang == "id"
            else
            "❌ Code not found.",
            show_alert=True,
        )
    # ------------------------------------------------------------------------
    # Get bot username
    # ------------------------------------------------------------------------
    me = await call.bot.get_me()
    bot_username = me.username
    if not bot_username:
        return await call.answer(
            "❌ Bot username belum dikonfigurasi."
            if lang == "id"
            else
            "❌ Bot username is not configured.",
            show_alert=True,
        )
    # ------------------------------------------------------------------------
    # Create Telegram deep link
    # ------------------------------------------------------------------------
    target = f"https://t.me/{bot_username}?start={quote(code)}"
    share_text_id = (
        "🤖 Coba code Telegram ini dari Marketplace!"
    )
    share_text_en = (
        "🤖 Check out this Telegram code from the Marketplace!"
    )
    share_url = (
        "https://t.me/share/url?"
        f"url={quote(target)}&"
        f"text={quote(share_text_id if lang == 'id' else share_text_en)}"
    )
    # ------------------------------------------------------------------------
    # Text
    # ------------------------------------------------------------------------
    if lang == "en":
        text = (
            "📤 <b>SHARE CODE</b>\n\n"
            "Share this code with friends or potential buyers.\n"
            "Every successful purchase increases the 3-step free-unlock "
            "progress for this code."
        )
        share_now = "📤 Share Now"
        progress = "🎁 Check Progress"
        back = "⬅️ Back"
    else:
        text = (
            "📤 <b>BAGIKAN CODE</b>\n\n"
            "Bagikan code ini ke teman atau calon pembeli.\n"
            "Setiap pembelian berhasil akan menambah progress "
            "gratis 3 tahap untuk code ini."
        )
        share_now = "📤 Bagikan Sekarang"
        progress = "🎁 Cek Progress"
        back = "⬅️ Kembali"
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=share_now,
                    url=share_url,
                )
            ],
            [
                InlineKeyboardButton(
                    text=progress,
                    callback_data=f"freeopen:{code}",
                )
            ],
            [
                InlineKeyboardButton(
                    text=back,
                    callback_data=f"market:{code}",
                )
            ],
        ]
    )
    try:
        await safe_edit_message(
            call,
            text,
            keyboard,
        )
    finally:
        await call.answer()
# ============================================================================
# MARKETPLACE - MOST REVIEWED
# ============================================================================
@router.callback_query(F.data == "market_reviews")
async def market_reviews(call: CallbackQuery):
    lang = await lang_of(call.from_user.id)
    pool = await get_pool()
    rows = await pool.fetch(
        """
        SELECT
            f.code,
            f.title,
            COALESCE(f.review_count, 0) AS review_count,
            COALESCE(f.rating, 0) AS rating,
            COALESCE(f.sold, 0) AS sold
        FROM files f
        WHERE COALESCE(f.review_count, 0) > 0
        ORDER BY
            review_count DESC,
            rating DESC,
            sold DESC
        LIMIT 20
        """
    )
    # ------------------------------------------------------------------------
    # Header
    # ------------------------------------------------------------------------
    if lang == "en":
        text = (
            "💬 <b>MOST REVIEWED CODES</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
        )
        empty = "No reviews yet."
        marketplace = "⬅️ Marketplace"
        review_label = "reviews"
        sold_label = "sold"
    else:
        text = (
            "💬 <b>CODE PALING BANYAK DIREVIEW</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
        )
        empty = "Belum ada review."
        marketplace = "⬅️ Marketplace"
        review_label = "review"
        sold_label = "terjual"
    # ------------------------------------------------------------------------
    # Empty
    # ------------------------------------------------------------------------
    if not rows:
        text += f"📭 {empty}"
    # ------------------------------------------------------------------------
    # Rows
    # ------------------------------------------------------------------------
    rows_kb = []
    for i, row in enumerate(rows, 1):
        code = str(row["code"])
        title = str(row["title"] or code)
        safe_title = escape(title)
        review_count = int(row["review_count"] or 0)
        sold = int(row["sold"] or 0)
        try:
            rating = float(row["rating"] or 0)
        except (TypeError, ValueError):
            rating = 0.0
        text += (
            f"{i}. <b>{safe_title}</b>\n"
            f"💬 {review_count} {review_label} • "
            f"⭐ {rating:.1f} • "
            f"🔥 {sold} {sold_label}\n\n"
        )
        # Telegram callback_data has a size limit.
        # Code should normally be short, but truncate defensively.
        callback_code = code[:40]
        button_title = title[:25]
        rows_kb.append(
            [
                InlineKeyboardButton(
                    text=f"💬 {button_title}",
                    callback_data=f"market:{callback_code}",
                )
            ]
        )
    # ------------------------------------------------------------------------
    # Back button
    # ------------------------------------------------------------------------
    rows_kb.append(
        [
            InlineKeyboardButton(
                text=marketplace,
                callback_data="marketplace",
            )
        ]
    )
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=rows_kb
    )
    try:
        await safe_edit_message(
            call,
            text,
            keyboard,
        )
    finally:
        await call.answer()
