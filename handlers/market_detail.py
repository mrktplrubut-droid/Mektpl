from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

from database import fetchrow


router = Router()


@router.callback_query(F.data.startswith("market:"))
async def market_detail(call: CallbackQuery):

    code = call.data.split(":", 1)[1]


    file = await fetchrow(
        """
        SELECT
            code,
            title,
            price,
            media_count,
            owner_id
        FROM files
        WHERE code=$1
        LIMIT 1
        """,
        code
    )


    if not file:

        return await call.answer(
            "❌ File tidak ditemukan.",
            show_alert=True
        )


    text = (
        "📦 <b>DETAIL FILE</b>\n\n"
        f"📝 Judul : <b>{file['title']}</b>\n"
        f"📁 Media : <b>{file['media_count']}</b>\n"
        f"💰 Harga : <b>Rp {file['price']:,}</b>\n\n"
        "Silakan tekan tombol beli untuk membuka file."
    )


    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="💳 Beli Sekarang",
                    callback_data=f"pay:{code}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="⬅️ Kembali",
                    callback_data="marketplace"
                )
            ]
        ]
    )


    await call.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=keyboard
    )


    await call.answer()
