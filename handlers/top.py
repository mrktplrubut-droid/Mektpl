from math import ceil

from aiogram import Router, F
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton
)

from database import get_pool


router = Router()

LIMIT = 10


def page_keyboard(page, max_page, prefix):
    buttons = []

    if page > 1:
        buttons.append(
            InlineKeyboardButton(
                text="⬅️",
                callback_data=f"{prefix}:{page-1}"
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
                callback_data=f"{prefix}:{page+1}"
            )
        )

    return InlineKeyboardMarkup(
        inline_keyboard=[
            buttons,
            [
                InlineKeyboardButton(
                    text="🏪 Kembali Store",
                    callback_data="store"
                )
            ]
        ]
    )


async def show_top_code(target, page=1):

    pool = await get_pool()

    msg = target.message if isinstance(target, CallbackQuery) else target

    total = await pool.fetchval(
        """
        SELECT COUNT(*)
        FROM files
        """
    )

    if total == 0:
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="↪️ Kembali",
                        callback_data="code"
                    )
                ]
            ]
        )

        await msg.edit_text(
            "❌ Belum ada code.",
            reply_markup=kb
        )

        if isinstance(target, CallbackQuery):
            await target.answer()

        return


    max_page = ceil(total / LIMIT)

    page = max(
        1,
        min(page, max_page)
    )

    offset = (page - 1) * LIMIT


    rows = await pool.fetch(
        """
        SELECT
            code,
            title,
            view_count
        FROM files
        ORDER BY
            view_count DESC,
            created_at DESC
        LIMIT $1 OFFSET $2
        """,
        LIMIT,
        offset
    )


    text = (
        "🔥 <b>TOP 10 CODE TERPOPULER</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
    )


    for i, row in enumerate(
        rows,
        start=offset + 1
    ):

        icon = (
            "🥇" if i == 1 else
            "🥈" if i == 2 else
            "🥉" if i == 3 else
            f"{i}."
        )

        text += (
            f"{icon} <b>{row['title']}</b>\n"
            f"🔑 <code>{row['code']}</code>\n"
            f"👁 Dibuka : {row['view_count']}x\n\n"
        )


    await msg.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=page_keyboard(
            page,
            max_page,
            "top"
        )
    )

    if isinstance(target, CallbackQuery):
        await target.answer()



# =========================
# BUTTON TOP 10
# =========================

@router.callback_query(F.data == "top_code")
async def top_open(call: CallbackQuery):

    await show_top_code(
        call,
        1
    )



# =========================
# PAGINATION
# =========================

@router.callback_query(F.data.startswith("top:"))
async def top_page(call: CallbackQuery):

    page = int(
        call.data.split(":")[1]
    )

    await show_top_code(
        call,
        page
    )



@router.callback_query(F.data == "ignore")
async def ignore(call: CallbackQuery):

    await call.answer()



# =========================
# COMMAND
# =========================

async def top_command(message: Message):

    await show_top_code(
        message,
        1
    )
