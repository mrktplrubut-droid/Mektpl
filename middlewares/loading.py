"""Global callback loading feedback for every inline callback button."""
from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery

def loading_text(data: str | None) -> str:
    value = (data or "").lower()
    if value.startswith(("page:", "all:", "allnext:", "freeopen:", "freeshare:", "sharecheck:")):
        return "⏳ Memuat media..."
    if value.startswith(("pay:", "premium_buy:", "vvip", "manual:", "cashi:", "paymentcheck:")):
        return "⏳ Memproses pembayaran..."
    if value.startswith(("market", "top_", "category_", "search", "favorite:", "rating:", "rate:", "like:", "dislike:")):
        return "⏳ Memuat..."
    if value.startswith(("account", "creator", "withdraw", "ewallet")):
        return "⏳ Memuat akun..."
    if value.startswith(("upfile", "getfile")):
        return "⏳ Menyiapkan..."
    if value.startswith("admin"):
        return "⏳ Memuat panel admin..."
    return "⏳ Memproses..."

class CallbackLoadingMiddleware(BaseMiddleware):
    """ACK every callback immediately; Telegram displays the native spinner on the pressed button."""
    async def __call__(self, handler, event, data):
        if isinstance(event, CallbackQuery):
            try:
                await event.answer(loading_text(event.data), show_alert=False)
            except Exception:
                pass
        return await handler(event, data)
