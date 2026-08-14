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


def page_keyboard(page, max_page):

    buttons = []

    if page > 1:
        buttons.append(
            InlineKeyboardButton(
                text="⬅️",
                callback_data=f"market_purchase:{page-1}"
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
                callback_data=f"market_purchase:{page+1}"
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


async def show_purchase(call: CallbackQuery, page: int):

    total = await fetchval(
        """
        SELECT COUNT(*)
        FROM file_purchases
        WHERE user_id=$1
          AND status='paid'
        """,
        call.from_user.id
    )

    if total == 0:

        return await call.message.edit_text(
            "🛍 <b>PEMBELIAN SAYA</b>\n\nBelum ada file yang pernah dibeli.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="⬅️ Marketplace",
                            callback_data="marketplace"
                        )
                    ]
                ]
            )
        )

    max_page = ceil(total / LIMIT)

    page = max(1, min(page, max_page))

    offset = (page - 1) * LIMIT

    rows = await fetch(
        """
        SELECT
            f.code,
            f.title,
            f.media_count,
            f.price
        FROM file_purchases p
        JOIN files f
            ON f.code=p.file_code
        WHERE p.user_id=$1
          AND p.status='paid'
        ORDER BY p.created_at DESC
        LIMIT $2 OFFSET $3
        """,
        call.from_user.id,
        LIMIT,
        offset
    )

    text = "🛍 <b>PEMBELIAN SAYA</b>\n━━━━━━━━━━━━━━━━━━\n\n"

    kb = []

    for i, row in enumerate(rows, start=offset + 1):

        text += (
            f"{i}. <b>{row['title']}</b>\n"
            f"📁 {row['media_count']} Media\n"
            f"💰 Rp {row['price']:,}\n\n"
        )

        kb.append([
            InlineKeyboardButton(
                text=f"📂 {row['title'][:30]}",
                callback_data=f"page:{row['code']}:1"
            )
        ])

    nav = page_keyboard(page, max_page)

    kb.extend(nav.inline_keyboard)

    await call.message.edit_text(
        text.replace(",", "."),
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=kb
        )
    )


@router.callback_query(F.data == "market_purchase")
async def purchase_menu(call: CallbackQuery):

    await call.answer()

    await show_purchase(call, 1)


@router.callback_query(F.data.startswith("market_purchase:"))
async def purchase_page(call: CallbackQuery):

    await call.answer()

    page = int(call.data.split(":")[1])

    await show_purchase(call, page)


@router.callback_query(F.data == "ignore")
async def ignore(call: CallbackQuery):

    await call.answer()
