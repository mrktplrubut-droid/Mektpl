from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

from database import fetchrow, execute

router = Router()


@router.callback_query(F.data.startswith("market:"))
async def market_detail(call: CallbackQuery):

    await call.answer()

    code = call.data.split(":", 1)[1]

    file = await fetchrow(
        """
        SELECT
            code,
            title,
            description,
            category,
            price,
            media_count,
            owner_id,
            sold,
            views,
            rating,
            review_count,
            is_paid
        FROM files
        WHERE code = $1
        LIMIT 1
        """,
        code
    )

    if not file:
        return await call.answer(
            "❌ File tidak ditemukan.",
            show_alert=True
        )

    # Tambah jumlah view
    await execute(
        """
        UPDATE files
        SET views = views + 1
        WHERE code = $1
        """,
        code
    )

    text = (
        "📦 <b>DETAIL FILE</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"

        f"📝 <b>{file['title']}</b>\n\n"

        f"📂 <b>Kategori :</b> {file['category'] or 'Lainnya'}\n"
        f"📁 <b>Total Media :</b> {file['media_count']}\n"
        f"💰 <b>Harga :</b> Rp {file['price']:,}\n"
        f"👤 <b>Seller :</b> <code>{file['owner_id']}</code>\n\n"

        f"🔥 <b>Terjual :</b> {file['sold']}\n"
        f"👀 <b>Dilihat :</b> {file['views'] + 1}\n"
        f"⭐ <b>Rating :</b> {float(file['rating']):.1f} ({file['review_count']} Review)\n\n"

        "📝 <b>Deskripsi</b>\n"
        f"{file['description'] or 'Tidak ada deskripsi.'}"
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
                    text="❤️ Favorit",
                    callback_data=f"fav:{code}"
                ),
                InlineKeyboardButton(
                    text="⭐ Review",
                    callback_data=f"review:{code}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="📤 Bagikan",
                    callback_data=f"share:{code}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="⬅️ Marketplace",
                    callback_data="marketplace"
                )
            ]
        ]
    )

    await call.message.edit_text(
        text.replace(",", "."),
        parse_mode="HTML",
        reply_markup=keyboard
    )
