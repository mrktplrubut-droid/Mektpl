from aiogram import Router, F
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton
)

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
            is_paid,

            COALESCE(sold,0) AS sold,
            COALESCE(views,0) AS views,
            COALESCE(rating,0) AS rating,
            COALESCE(review_count,0) AS review_count,
            COALESCE(favorite_count,0) AS favorite_count

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

    # Tambah view
    await execute(
        """
        UPDATE files
        SET views = COALESCE(views,0)+1
        WHERE code=$1
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
        f"👁 <b>Dilihat :</b> {file['views'] + 1}\n"
        f"❤️ <b>Favorit :</b> {file['favorite_count']}\n"
        f"⭐ <b>Rating :</b> {float(file['rating']):.1f} ({file['review_count']} Review)\n\n"

        "📝 <b>Deskripsi</b>\n"
        f"{file['description'] or 'Tidak ada deskripsi.'}"
    ).replace(",", ".")

    keyboard = []

    if file["is_paid"]:
        keyboard.append([
            InlineKeyboardButton(
                text=f"💳 Beli Rp {file['price']:,}".replace(",", "."),
                callback_data=f"pay:{code}"
            )
        ])
    else:
        keyboard.append([
            InlineKeyboardButton(
                text="📂 Buka File",
                callback_data=f"page:{code}:1"
            )
        ])

    keyboard.extend([
        [
            InlineKeyboardButton(
                text="❤️ Tambah Favorit",
                callback_data=f"favorite:{code}"
            ),
            InlineKeyboardButton(
                text="⭐ Rating",
                callback_data=f"rating:{code}"
            )
        ],
        [
            InlineKeyboardButton(
                text="💬 Review",
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
    ])

    await call.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=keyboard
        )
    )
