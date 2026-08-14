from aiogram import Router, F
from aiogram.types import CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

from database import fetch, fetchrow

router = Router()


@router.callback_query(F.data == "marketplace")
async def marketplace_menu(call: CallbackQuery):

    await call.answer()

    stats = await fetchrow("""
        SELECT
            COUNT(*) AS total_files,
            COUNT(DISTINCT seller_id) AS total_sellers,
            COALESCE(SUM(sold),0) AS total_sold
        FROM files
        WHERE is_paid = true
    """)

    files = await fetch("""
        SELECT
            code,
            title,
            price,
            media_count,
            sold,
            rating
        FROM files
        WHERE is_paid = true
        ORDER BY created_at DESC
        LIMIT 5
    """)

    kb = InlineKeyboardBuilder()

    text = (
        "🛒 <b>MARKETPLACE</b>\n"
        "━━━━━━━━━━━━━━\n\n"
        f"📦 <b>Total File :</b> {stats['total_files']}\n"
        f"👥 <b>Seller :</b> {stats['total_sellers']}\n"
        f"🛍 <b>Terjual :</b> {stats['total_sold']}\n\n"
        "🔥 <b>File Terbaru</b>\n\n"
    )

    if not files:

        text += "Belum ada file yang dijual."

    else:

        for f in files:

            text += (
                f"📦 <b>{f['title']}</b>\n"
                f"💰 Rp{f['price']:,}\n"
                f"📁 {f['media_count']} Media\n"
                f"🔥 {f['sold']} Terjual | ⭐ {float(f['rating']):.1f}\n\n"
            )

            kb.button(
                text=f"📦 {f['title'][:25]}",
                callback_data=f"market:{f['code']}"
            )

    kb.button(text="🔍 Cari File", callback_data="search_code")
    kb.button(text="🔥 Terlaris", callback_data="top_code")
    kb.button(text="🆕 Terbaru", callback_data="new_code")
    kb.button(text="📂 Kategori", callback_data="category_code")
    kb.button(text="🏷 Semua File", callback_data="market_all")
    kb.button(text="⭐ Rating", callback_data="market_rating")
    kb.button(text="❤️ Favorit", callback_data="market_favorite")
    kb.button(text="🛍 Pembelian Saya", callback_data="market_purchase")
    kb.button(text="🏠 Home", callback_data="home")

    kb.adjust(
        1,  # file
        1,
        1,
        1,
        1,
        2,
        2,
        1,
        1
    )

    await call.message.edit_text(
        text.replace(",", "."),
        parse_mode="HTML",
        reply_markup=kb.as_markup()
    )
