from aiogram import Router, F
from aiogram.types import CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

from database import fetch

router = Router()


@router.callback_query(F.data == "market_rating")
async def market_rating(call: CallbackQuery):

    await call.answer()

    rows = await fetch(
        """
        SELECT
            code,
            title,
            price,
            media_count,
            rating,
            sold
        FROM files
        WHERE is_paid=true
        ORDER BY rating DESC, sold DESC
        LIMIT 20
        """
    )

    kb = InlineKeyboardBuilder()

    text = "⭐ <b>RATING TERTINGGI</b>\n\n"

    if not rows:
        text += "Belum ada data."

    for row in rows:

        harga = (
            "Gratis"
            if row["price"] == 0
            else f"Rp{row['price']:,}".replace(",", ".")
        )

        text += (
            f"⭐ <b>{row['title']}</b>\n"
            f"💰 {harga}\n"
            f"📁 {row['media_count']} Media\n"
            f"🌟 {float(row['rating']):.1f}\n\n"
        )

        kb.button(
            text=f"⭐ {row['title'][:25]}",
            callback_data=f"market:{row['code']}"
        )

    kb.button(
        text="⬅️ Marketplace",
        callback_data="marketplace"
    )

    kb.adjust(1)

    await call.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=kb.as_markup()
    )
