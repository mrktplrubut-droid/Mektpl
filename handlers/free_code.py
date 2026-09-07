from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from database import get_pool
from utils.share_unlock import get_share_status, ensure_share_progress

router = Router()


@router.callback_query(F.data == "free_codes")
async def free_codes(call: CallbackQuery):
    pool = await get_pool()
    lang = (await pool.fetchval(
        "SELECT language FROM users WHERE user_id=$1", call.from_user.id
    )) or "id"

    rows = await pool.fetch(
        """
        SELECT
            f.code,
            COALESCE(f.title,f.code) AS title,
            COALESCE(f.media_count,0) AS media_count,
            COALESCE(f.is_paid,FALSE) AS is_paid
        FROM files f
        WHERE f.status='published'
        ORDER BY f.created_at DESC
        LIMIT 30
        """
    )

    if lang == "en":
        text = (
            "🎁 <b>SHARE UNLOCK</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "Share a code. Progress increases only when a genuinely new member "
            "opens the bot from your code share link.\n\n"
        )
    else:
        text = (
            "🎁 <b>SHARE UNLOCK</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "Bagikan code. Progress hanya bertambah jika member baru benar-benar "
            "membuka bot melalui link share code.\n\n"
        )

    buttons = []
    for row in rows:
        current, target, completed = await get_share_status(
            pool, row["code"], call.from_user.id,
            is_paid=bool(row["is_paid"]),
            media_count=int(row["media_count"] or 0),
        )
        if completed:
            status = f"🎉 {target}/{target}"
        else:
            status = f"📈 {current}/{target}"
        label = str(row["title"])[:22]
        buttons.append([
            InlineKeyboardButton(
                text=f"🎁 {label} • {status}",
                callback_data=f"freeopen:{row['code']}"
            )
        ])

    if not buttons:
        text += "📭 Belum ada code published."

    buttons += [
        [InlineKeyboardButton(text="🛍 Marketplace", callback_data="marketplace")],
        [InlineKeyboardButton(text="🏠 Home", callback_data="home")]
    ]
    await call.message.edit_text(
        text, parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )
    await call.answer()
