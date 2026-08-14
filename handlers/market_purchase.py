from math import ceil

from aiogram import Router, F
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton
)

from database import fetch, fetchval

router = Router()

LIMIT = 10


# =========================
# PAGINATION KEYBOARD
# =========================

def page_keyboard(page, max_page):

    buttons = []

    if page > 1:
        buttons.append(
            InlineKeyboardButton(
                text="⬅️",
                callback_data=f"market_purchase:{page - 1}"
            )
        )

    buttons.append(
        InlineKeyboardButton(
            text=f"{page}/{max_page}",
            callback_data="ignore"
        )
    )

    if page < max_page:
        buttons.append(
            InlineKeyboardButton(
                text="➡️",
                callback_data=f"market_purchase:{page + 1}"
            )
        )

    return InlineKeyboardMarkup(
        inline_keyboard=[
            buttons,
            [
                InlineKeyboardButton(
                    text="⬅️ Marketplace",
                    callback_data="marketplace"
                )
            ]
        ]
    )


# =========================
# SHOW PURCHASE
# =========================

async def show_purchase(call: CallbackQuery, page: int = 1):

    user_id = call.from_user.id

    # =========================
    # TOTAL PEMBELIAN
    # =========================

    total = await fetchval(
        """
        SELECT COUNT(*)
        FROM file_purchases
        WHERE user_id=$1
        """,
        user_id
    )

    total = total or 0

    # =========================
    # BELUM ADA PEMBELIAN
    # =========================

    if total == 0:

        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="⬅️ Marketplace",
                        callback_data="marketplace"
                    )
                ]
            ]
        )

        return await call.message.edit_text(
            "🛍 <b>PEMBELIAN SAYA</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "Belum ada file yang pernah dibeli.",
            parse_mode="HTML",
            reply_markup=keyboard
        )

    # =========================
    # PAGINATION
    # =========================

    max_page = ceil(total / LIMIT)

    page = max(
        1,
        min(page, max_page)
    )

    offset = (page - 1) * LIMIT

    # =========================
    # AMBIL DATA
    # =========================

    rows = await fetch(
        """
        SELECT
            f.code,
            f.title,
            f.media_count,
            f.price
        FROM file_purchases p
        JOIN files f
            ON f.code = p.code
        WHERE p.user_id=$1
        ORDER BY p.created_at DESC
        LIMIT $2 OFFSET $3
        """,
        user_id,
        LIMIT,
        offset
    )

    # =========================
    # TEXT
    # =========================

    text = (
        "🛍 <b>PEMBELIAN SAYA</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        f"📦 Total Pembelian : <b>{total}</b>\n"
        f"📄 Halaman : <b>{page}/{max_page}</b>\n\n"
    )

    keyboard = []

    # =========================
    # FILE LIST
    # =========================

    for i, row in enumerate(
        rows,
        start=offset + 1
    ):

        price = row["price"] or 0

        text += (
            f"{i}. <b>{row['title']}</b>\n"
            f"🔑 <code>{row['code']}</code>\n"
            f"📁 {row['media_count']} Media\n"
            f"💰 Rp {price:,}\n\n"
        )

        keyboard.append([
            InlineKeyboardButton(
                text=f"📂 {row['title'][:30]}",
                callback_data=f"page:{row['code']}:1"
            )
        ])

    # =========================
    # NAVIGATION
    # =========================

    nav = page_keyboard(
        page,
        max_page
    )

    keyboard.extend(
        nav.inline_keyboard
    )

    # =========================
    # SEND
    # =========================

    await call.message.edit_text(
        text.replace(",", "."),
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=keyboard
        )
    )


# =========================
# MENU
# =========================

@router.callback_query(
    F.data == "market_purchase"
)
async def purchase_menu(
    call: CallbackQuery
):

    await call.answer()

    await show_purchase(
        call,
        1
    )


# =========================
# PAGINATION
# =========================

@router.callback_query(
    F.data.startswith("market_purchase:")
)
async def purchase_page(
    call: CallbackQuery
):

    await call.answer()

    try:
        page = int(
            call.data.split(":")[1]
        )
    except (ValueError, IndexError):

        return await call.answer(
            "❌ Halaman tidak valid.",
            show_alert=True
        )

    await show_purchase(
        call,
        page
    )


# =========================
# IGNORE
# =========================

@router.callback_query(
    F.data == "ignore"
)
async def ignore(
    call: CallbackQuery
):

    await call.answer()
