from urllib.parse import quote
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from utils.force_sub import CHANNELS

def join_kb(bot_username: str | None = None, user_id: int | None = None, lang: str = "id"):
    ref_link = ""
    share_url = None
    if bot_username and user_id:
        ref_link = f"https://t.me/{bot_username}?start=ref_{user_id}"
        share_text = (
            "🤖 Ayo bergabung di bot marketplace! "
            "Upload, jual, beli dan bagikan code Telegram dengan mudah."
            if lang == "id"
            else "🤖 Join the marketplace bot! Upload, sell, buy and share Telegram code easily."
        )
        share_url = "https://t.me/share/url?" + f"url={quote(ref_link)}&text={quote(share_text)}"

    rows = []
    for idx, channel in enumerate(CHANNELS, 1):
        name = channel["name"] if lang == "id" else ("Main Channel" if idx == 1 else "Update Channel")
        rows.append([InlineKeyboardButton(text=f"📢 {name}", url=channel["url"])])

    if share_url:
        rows.append([InlineKeyboardButton(
            text="📤 Bagikan Referral" if lang == "id" else "📤 Share Referral",
            url=share_url
        )])
    rows.append([InlineKeyboardButton(
        text="✅ Saya Sudah Join" if lang == "id" else "✅ I Joined",
        callback_data="check_sub"
    )])
    return InlineKeyboardMarkup(inline_keyboard=rows)
