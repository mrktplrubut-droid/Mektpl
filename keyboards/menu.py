from aiogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)


def home_kb(user_id: int):

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
                    text="📦 Code",
                    callback_data="code"
                ),
                InlineKeyboardButton(
                    text="💰 Ewallet",
                    callback_data="ewallet"
                )
            ],

            [
                InlineKeyboardButton(
                    text="💸 Withdraw",
                    callback_data="withdraw"
                ),
                InlineKeyboardButton(
                    text="📊 Marketplace",
                    callback_data="marketplace"
                )
            ],

            [
                InlineKeyboardButton(
                    text="👤 Account",
                    callback_data="account"
                ),
                InlineKeyboardButton(
                    text="📢 Info Channel",
                    callback_data="channel"
                )
            ],

            [
                InlineKeyboardButton(
                    text="❓ Bantuan",
                    callback_data="help"
                )
            ]

        ]
    )
