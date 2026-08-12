from aiogram import Router, F
from aiogram.types import CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

from database import get_pool


router = Router()


@router.callback_query(F.data == "new_code")
async def new_code_menu(call: CallbackQuery):

    pool = await get_pool()

    rows = await pool.fetch(
        """
        SELECT
            code,
            title,
            price,
            view_count
        FROM files
        ORDER BY created_at DESC
        LIMIT 10
        """
    )


    if not rows:
        return await call.answer(
            "❌ Belum ada code baru.",
            show_alert=True
        )


    text = (
        "🆕 <b>CODE TERBARU</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
    )


    for i, row in enumerate(rows, 1):

        harga = (
            "Gratis"
            if row["price"] == 0
            else f"Rp{row['price']:,}"
        )

        text += (
            f"{i}. 📌 <b>{row['title']}</b>\n"
            f"🔑 <code>{row['code']}</code>\n"
            f"💰 Harga : {harga}\n"
            f"👁 Dibuka : {row['view_count']}x\n\n"
        )


    kb = InlineKeyboardBuilder()

    kb.button(
        text="⬅️ Kembali",
        callback_data="code"
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

    await call.answer()
