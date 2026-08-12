from urllib.parse import quote
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def join_kb(bot_username: str, user_id: int):

    ref_link = f"https://t.me/{bot_username}?start=ref_{user_id}"

    share_text = (
        "🤖 Ayo bergabung di BOT MARKET!\n\n"
        "🎁 Daftar menggunakan link referral saya dan mulai sekarang juga."
    )

    share_url = (
        "https://t.me/share/url?"
        f"url={quote(ref_link)}&"
        f"text={quote(share_text)}"
    )

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📢 Join Channel 1",
                    url="https://t.me/+CUAmQ49VFMw1MmRh"
                )
            ],
            [
                InlineKeyboardButton(
                    text="📢 Join Channel 2",
                    url="https://t.me/+0ddS3Ha4c2pkNmJl"
                )
            ],
            [
                InlineKeyboardButton(
                    text="📤 Bagikan Referral",
                    url=share_url
                )
            ],
            [
                InlineKeyboardButton(
                    text="✅ Saya Sudah Join",
                    callback_data="check_join"
                )
            ]
        ]
    )
