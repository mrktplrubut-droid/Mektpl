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
    code = call.data.split(":", 1)[1]

    # Jawab callback agar tidak timeout
    try:
        await call.answer("⏳ Processing...")
    except:
        pass

    pool = await get_pool()

    file = await pool.fetchrow(
        """
        SELECT *
        FROM files
        WHERE LOWER(TRIM(code)) = LOWER(TRIM($1))
        LIMIT 1
        """,
        code
    )

    if not file:
        try:
            await call.answer(
                "❌ File tidak ditemukan.",
                show_alert=True
            )
        except:
            pass
        return

    # Ambil status user
    user_level = await get_user_status(
        pool,
        call.from_user.id
    )

    # VIP/Kreator harus tetap dicek di server saat Open All.
    # Ini mencegah bypass melalui callback langsung.
    from utils.user import has_premium_access
    paid = bool(file.get("is_paid"))
    if paid:
        purchased = await pool.fetchval(
            """SELECT EXISTS(SELECT 1 FROM file_purchases
               WHERE user_id=$1 AND file_code=$2 AND status='paid')""",
            call.from_user.id, code
        )
        owner = call.from_user.id == file.get("owner_id")
        creator = await pool.fetchval(
            """SELECT COALESCE(is_creator,FALSE) AND COALESCE(creator_status,'none')='approved'
               FROM users WHERE user_id=$1""", call.from_user.id
        ) or False
        if not (owner or purchased or creator):
            ok, reason = await has_premium_access(pool, call.from_user.id, code, consume=True)
            if not ok:
                if reason == "limit":
                    return await call.answer("⏱️ VIP jam sudah mencapai 3 code.", show_alert=True)
                return await call.answer("🔒 Code ini perlu dibayar atau gunakan VIP/Kreator aktif.", show_alert=True)

    # Kirim semua media
    await send_all(
        bot=call.bot,
        chat_id=call.message.chat.id,
        code=code,
        file=file,
        user_level=user_level
    )
