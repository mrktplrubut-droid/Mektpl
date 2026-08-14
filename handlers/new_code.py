from aiogram import Router, F
from aiogram.types import CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

from database import get_pool


router = Router()


@router.callback_query(F.data == "new_code")
async def new_code_menu(call: CallbackQuery):

    await call.answer()

    pool = await get_pool()

    rows = await pool.fetch(
        """
        SELECT
            code,
            title,
            price,
            media_count,
            views,
            rating,
            is_premium
        FROM files
        ORDER BY created_at DESC
        LIMIT 10
        """
    )

    if not rows:
        return await call.message.edit_text(
            "🆕 <b>CODE TERBARU</b>\n\n"
            "Belum ada file yang tersedia.",
            parse_mode="HTML"
        )

    text = (
        "🆕 <b>CODE TERBARU</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "Berikut file terbaru yang baru dipublikasikan:\n\n"
    )

    kb = InlineKeyboardBuilder()

    for i, row in enumerate(rows, 1):

        harga = (
            "Gratis"
            if not row["price"]
            else f"Rp {row['price']:,}".replace(",", ".")
        )

        premium = " 👑" if row["is_premium"] else ""

        rating = (
            f"{float(row['rating']):.1f}"
            if row["rating"] is not None
            else "0.0"
        )

        text += (
            f"{i}. <b>{row['title']}</b>{premium}\n"
            f"💰 {harga}\n"
            f"📁 {row['media_count']} Media\n"
            f"👁 {row['views']} Dilihat\n"
            f"⭐ {rating}\n\n"
        )

        kb.button(
            text=f"📦 {row['title'][:30]}",
            callback_data=f"market:{row['code']}"
        )

    kb.button(
        text="🛒 Marketplace",
        callback_data="marketplace"
    )

    kb.button(
        text="🏠 Home",
        callback_data="home"
    )

    kb.adjust(1)

    await call.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=kb.as_markup()
    )
