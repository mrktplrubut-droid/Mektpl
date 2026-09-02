from aiogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)


def home_kb(user_id: int, lang: str = "id"):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📤 Upload File" if lang == "id" else "📤 Upload",
                    callback_data="upfile"
                ),
                InlineKeyboardButton(
                    text="📥 Get File" if lang == "id" else "📥 Get Code",
                    callback_data="getfile"
                )
            ],
            [
                InlineKeyboardButton(
                    text="👤 Account" if lang == "id" else "👤 Account",
                    callback_data="account"
                ),
                InlineKeyboardButton(
                    text="🛍️ Marketplace",
                    callback_data="marketplace"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🎨 Kreator" if lang == "id" else "🎨 Creator",
                    callback_data="creator"
                ),
                InlineKeyboardButton(
                    text="📂 Menu Lainnya" if lang == "id" else "📂 More Menu",
                    callback_data="menu_lainnya"
                ),
                InlineKeyboardButton(
                    text="❓ Bantuan" if lang == "id" else "❓ Help",
                    callback_data="help"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🌐 Bahasa" if lang == "id" else "🌐 Language",
                    callback_data="change_language"
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
                    text="📢 Info Channel",
                    callback_data="channel"
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
