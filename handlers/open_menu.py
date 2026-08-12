from aiogram import Router, F
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton
)

from database import get_pool
from handlers.sendall import send_all
from utils.user import get_user_status  # 🔥 TAMBAH INI

router = Router()


def open_keyboard(code):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📂 Open Page",
                    callback_data=f"page:{code}:1"
                )
            ],
            [
                InlineKeyboardButton(
                    text="📤 Open All",
                    callback_data=f"all:{code}"
                )
            ]
        ]
    )


@router.callback_query(F.data.startswith("all:"))
async def open_all(call: CallbackQuery):
    code = call.data.split(":")[1]

    # ✅ jawab dulu biar ga expired
    try:
        await call.answer("⏳ Processing...")
    except:
        pass

    pool = await get_pool()

    file = await pool.fetchrow(
        """
        SELECT *
        FROM files
        WHERE LOWER(code)=LOWER($1)
        LIMIT 1
        """,
        code
    )

    if not file:
        try:
            await call.answer("❌ File tidak ditemukan", show_alert=True)
        except:
            pass
        return

    # 🔥 AMBIL USER LEVEL
    user_level = await get_user_status(
        pool,
        call.from_user.id
    )

    # 🔥 KIRIM KE send_all
    await send_all(
        bot=call.bot,
        chat_id=call.message.chat.id,
        code=code,
        file=file,
        user_level=user_level  # 🔥 WAJIB
    )
