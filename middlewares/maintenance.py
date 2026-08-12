from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery
from database import get_pool
from handlers.admin.admins import is_admin
from config import BOT_USERNAME


class MaintenanceMiddleware(BaseMiddleware):

    async def __call__(self, handler, event, data):

        user = None

        if isinstance(event, Message):
            user = event.from_user

        elif isinstance(event, CallbackQuery):
            user = event.from_user

        if user:

            pool = await get_pool()

            status = await pool.fetchval(
                "SELECT value FROM settings WHERE key='maintenance'"
            )

            # maintenance aktif
            if status == "on" and not is_admin(user.id):

                text = await pool.fetchval(
                    "SELECT value FROM settings WHERE key='maintenance_text'"
                )

                text = text or "🚧 Bot sedang maintenance."

                if isinstance(event, Message):
                    try:
                        await event.delete()
                    except:
                        pass

                    await event.answer(text)

                elif isinstance(event, CallbackQuery):
                    await event.answer(
                        text,
                        show_alert=True
                    )

                return

        return await handler(event, data)
