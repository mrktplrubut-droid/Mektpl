from math import ceil

from aiogram import Router, F
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from database import get_pool


router = Router()

LIMIT = 10


async def show_top_code(target, page=1):

    pool = await get_pool()

    msg = target.message if isinstance(target, CallbackQuery) else target

    total = await pool.fetchval(
        """
        SELECT COUNT(*)
        FROM files
        """
    )

    if not total:

        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="🏪 Marketplace",
                        callback_data="marketplace"
                    )
                ]
            ]
        )

        await msg.edit_text(
            "❌ Belum ada file.",
            reply_markup=kb
        )

        if isinstance(target, CallbackQuery):
            await target.answer()

        return

    max_page = ceil(total / LIMIT)
    page = max(1, min(page, max_page))
    offset = (page - 1) * LIMIT

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
        ORDER BY
            views DESC,
            created_at DESC
        LIMIT $1 OFFSET $2
        """,
        LIMIT,
        offset
    )

    text = (
        "🔥 <b>TOP FILE TERPOPULER</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
    )

    kb = InlineKeyboardBuilder()

    for i, row in enumerate(rows, start=offset + 1):

        if i == 1:
            icon = "🥇"
        elif i == 2:
            icon = "🥈"
        elif i == 3:
            icon = "🥉"
        else:
            icon = f"{i}."

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
            f"{icon} <b>{row['title']}</b>{premium}\n"
            f"💰 {harga}\n"
            f"📁 {row['media_count']} Media\n"
            f"👁 {row['views']} Dilihat\n"
            f"⭐ {rating}\n\n"
        )

        kb.button(
            text=f"📦 {row['title'][:30]}",
            callback_data=f"market:{row['code']}"
        )

    nav = []

    if page > 1:
        nav.append(
            InlineKeyboardButton(
                text="⬅️",
                callback_data=f"top:{page-1}"
            )
        )

    nav.append(
        InlineKeyboardButton(
            text=f"{page}/{max_page}",
            callback_data="ignore"
        )
    )

    if page < max_page:
        nav.append(
            InlineKeyboardButton(
                text="➡️",
                callback_data=f"top:{page+1}"
            )
        )

    kb.row(*nav)

    kb.button(
        text="🏪 Marketplace",
        callback_data="marketplace"
    )

    kb.adjust(1)

    await msg.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=kb.as_markup()
    )

    if isinstance(target, CallbackQuery):
        await target.answer()


# =========================
# BUTTON TOP
# =========================

@router.callback_query(F.data == "top_code")
async def top_open(call: CallbackQuery):
    await show_top_code(call, 1)


# =========================
# PAGINATION
# =========================

@router.callback_query(F.data.startswith("top:"))
async def top_page(call: CallbackQuery):

    page = int(call.data.split(":")[1])

    await show_top_code(call, page)


@router.callback_query(F.data == "ignore")
async def ignore(call: CallbackQuery):
    await call.answer()


# =========================
# COMMAND
# =========================

async def top_command(message: Message):
    await show_top_code(message, 1)
