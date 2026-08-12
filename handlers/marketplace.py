from aiogram import Router, F
from aiogram.types import CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

from database import fetch


router = Router()


# =====================================
# OPEN MARKETPLACE
# =====================================

@router.callback_query(F.data=="marketplace")
async def marketplace_menu(call: CallbackQuery):

    await call.answer()


    files = await fetch(
        """
        SELECT
            code,
            title,
            price,
            media_count
        FROM files
        WHERE is_paid=true
        ORDER BY id DESC
        LIMIT 10
        """
    )


    if not files:

        return await call.message.edit_text(
            (
                "🛒 <b>MARKETPLACE</b>\n\n"
                "Belum ada file yang dijual."
            ),
            parse_mode="HTML"
        )


    kb = InlineKeyboardBuilder()


    text = (
        "🛒 <b>MARKETPLACE</b>\n\n"
        "Pilih file yang ingin dibeli:\n\n"
    )


    for f in files:

        text += (
            f"📦 <b>{f['title']}</b>\n"
            f"💰 Rp{f['price']:,}\n"
            f"📁 {f['media_count']} Media\n\n"
        )


        kb.button(
            text=f"📦 {f['title'][:25]}",
            callback_data=f"market:{f['code']}"
        )


    kb.button(
        text="🏠 Home",
        callback_data="home"
    )


    kb.adjust(1)


    await call.message.edit_text(
        text.replace(",", "."),
        parse_mode="HTML",
        reply_markup=kb.as_markup()
    )
