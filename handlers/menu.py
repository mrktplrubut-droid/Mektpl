from aiogram import Router, F
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)

router = Router()


async def home_kb(user_id: int):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📤 Upload File",
                    callback_data="upfile"
                ),
                InlineKeyboardButton(
                    text="📥 Get File",
                    callback_data="getfile"
                )
            ],
            [
                InlineKeyboardButton(
                    text="👤 Account",
                    callback_data="account"
                ),
                InlineKeyboardButton(
                    text="📊 Marketplace",
                    callback_data="marketplace"
                )
            ],
            [
                InlineKeyboardButton(
                    text="💎 VIP / Kreator",
                    callback_data="premium"
                )
            ],
            [
                InlineKeyboardButton(
                    text="📂 Menu Lainnya",
                    callback_data="menu_lainnya"
                ),
                InlineKeyboardButton(
                    text="❓ Bantuan",
                    callback_data="help"
                )
            ]
        ]
    )


def other_menu_kb():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📦 Code",
                    callback_data="code"
                ),
                InlineKeyboardButton(
                    text="💸 Withdraw",
                    callback_data="withdraw"
                )
            ],
            [
                InlineKeyboardButton(
                    text="📢 Info Channel",
                    callback_data="channel_info"
                )
            ],
            [
                InlineKeyboardButton(
                    text="⬅️ Kembali",
                    callback_data="home"
                )
            ]
        ]
    )


@router.callback_query(F.data == "menu_lainnya")
async def menu_lainnya(callback: CallbackQuery):
    await callback.message.edit_reply_markup(
        reply_markup=other_menu_kb()
    )
    await callback.answer()


@router.callback_query(F.data == "home")
async def back_home(callback: CallbackQuery):
    await callback.message.edit_reply_markup(
        reply_markup=await home_kb(callback.from_user.id)
    )
    await callback.answer()
