"""
Global callback loading feedback.

Shows an immediate Telegram callback toast before the actual handler starts,
so database/API operations do not look like a frozen button.
"""
from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery


class CallbackLoadingMiddleware(BaseMiddleware):
    def __init__(self, text: str = "⏳ Memproses..."):
        self.text = text

    async def __call__(self, handler, event, data):
        if isinstance(event, CallbackQuery):
            try:
                await event.answer(self.text, show_alert=False)
            except Exception:
                # The real handler is still allowed to run if the callback
                # has already been acknowledged/expired.
                pass
        return await handler(event, data)
