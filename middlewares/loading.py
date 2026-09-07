"""
Global callback loading feedback.

Every inline callback is acknowledged immediately so Telegram never looks
frozen while DB/API work is running.  The actual handler remains responsible
for its final result.
"""
from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery


def loading_text(data: str | None) -> str:
    value = (data or "").lower()
    if value.startswith(("page:", "all:", "freeopen:", "freeshare:")):
        return "📂 Memuat file..."
    if value.startswith(("pay:", "premium_buy:", "vvip")):
        return "💳 Memproses..."
    if value.startswith(("market", "top_", "category_", "search")):
        return "🛍️ Memuat marketplace..."
    if value.startswith(("account", "creator", "withdraw", "ewallet")):
        return "👤 Memuat akun..."
    if value.startswith(("upfile", "getfile")):
        return "📦 Menyiapkan..."
    if value.startswith("admin"):
        return "🛠️ Memuat panel admin..."
    return "⏳ Memproses..."


class CallbackLoadingMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        if isinstance(event, CallbackQuery):
            try:
                await event.answer(loading_text(event.data), show_alert=False)
            except Exception:
                pass
        return await handler(event, data)
