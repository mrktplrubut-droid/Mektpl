from aiogram import Router, F
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton
)

from database import get_pool

router = Router()

BOT_USERNAME = "botmarketRobot"  # Ganti dengan username bot


async def open_account(message: Message, user_id: int):

    pool = await get_pool()

    user = await pool.fetchrow(
        """
        SELECT referral_count
        FROM users
        WHERE user_id=$1
        """,
        user_id
    )

    referral_count = user["referral_count"] if user else 0
    ref_link = f"https://t.me/{BOT_USERNAME}?start=ref_{user_id}"

    text = (
        "👤 <b>ACCOUNT INFO</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        f"🆔 <b>User ID</b>\n"
        f"<code>{user_id}</code>\n\n"
        "🎯 <b>REFERRAL</b>\n"
        f"👥 Total Undangan : <b>{referral_count}</b>\n\n"
        "🔗 <b>Link Referral</b>\n"
        f"<code>{ref_link}</code>\n"
    )

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📂 My Code",
                    callback_data="my_code"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🏦 Withdraw",
                    callback_data="withdraw"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔙 Kembali",
                    callback_data="home"
                )
            ]
        ]
    )

    await message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=kb,
        disable_web_page_preview=True
    )


@router.callback_query(F.data == "account")
async def account_handler(call: CallbackQuery):

    await open_account(
        call.message,
        call.from_user.id
    )

    await call.answer()


@router.message(F.text.in_(["👤 Akun", "👤 Account"]))
async def account(message: Message):

    loading = await message.answer("⏳ Loading...")

    await open_account(
        loading,
        message.from_user.id
    )
