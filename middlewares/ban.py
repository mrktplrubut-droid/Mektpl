from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery

from database import get_pool


class BanMiddleware(BaseMiddleware):

    async def __call__(self, handler, event, data):

        if isinstance(event, (Message, CallbackQuery)):
            user_id = event.from_user.id
        else:
            return await handler(event, data)

        pool = await get_pool()

        user = await pool.fetchrow(
            """
            SELECT is_banned
            FROM users
            WHERE user_id=$1
            """,
            user_id
        )

        if user and user["is_banned"]:

            if isinstance(event, Message):
                await event.answer("🚫 Akun Anda telah diblokir.")
            else:
                await event.answer(
                    "🚫 Akun Anda diblokir.",
                    show_alert=True
                )

            return

        return await handler(event, data)
