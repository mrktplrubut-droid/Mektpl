from aiogram import Router, F
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton
)

from database import fetchrow, execute

router = Router()


@router.callback_query(F.data.startswith("market:"))
async def market_detail(call: CallbackQuery):

    await call.answer()

    code = call.data.split(":", 1)[1]

    file = await fetchrow(
        """
        SELECT
            code,
            title,
            description,
            category,
            price,
            media_count,
            owner_id,
            is_paid,

            COALESCE(sold, 0) AS sold,
            COALESCE(views, 0) AS views,
            COALESCE(rating, 0) AS rating,
            COALESCE(review_count, 0) AS review_count,
            COALESCE(favorite_count, 0) AS favorite_count,
            COALESCE(likes, 0) AS likes,
            COALESCE(dislikes, 0) AS dislikes,
            COALESCE(free_progress, 0) AS free_progress,
            COALESCE(free_unlock_enabled, TRUE) AS free_unlock_enabled

        FROM files
        WHERE code = $1
        LIMIT 1
        """,
        code
    )

    if not file:
        return await call.answer(
            "❌ File tidak ditemukan.",
            show_alert=True
        )

    # Satu view unik per user/file. Semua tersimpan di database.
    viewed = await fetchrow(
        """
        INSERT INTO file_views(user_id, file_code)
        VALUES($1, $2)
        ON CONFLICT (user_id, file_code) DO NOTHING
        RETURNING user_id
        """,
        call.from_user.id,
        code
    )
    if viewed:
        await execute(
            """
            UPDATE files
            SET views = COALESCE(views, 0) + 1,
                view_count = COALESCE(view_count, 0) + 1
            WHERE code = $1
            """,
            code
        )

    current_views = int(file["views"] or 0) + (1 if viewed else 0)
    price = file["price"] or 0

    text = (
        "📦 <b>DETAIL FILE</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"

        f"📝 <b>{file['title']}</b>\n\n"

        f"📂 <b>Kategori :</b> {file['category'] or 'Lainnya'}\n"
        f"📁 <b>Total Media :</b> {file['media_count']}\n"
        f"💰 <b>Harga :</b> Rp {price:,}\n"
        f"👤 <b>Seller :</b> <code>{file['owner_id']}</code>\n\n"

        f"🔥 <b>Terjual :</b> {file['sold']}\n"
        f"👁 <b>Dilihat :</b> {current_views}\n"
        f"❤️ <b>Suka :</b> {file['likes']}  |  👎 <b>Tidak suka :</b> {file['dislikes']}\n"
        f"❤️ <b>Favorit :</b> {file['favorite_count']}\n"
        f"⭐ <b>Rating :</b> {float(file['rating']):.1f} ({file['review_count']} Review)\n\n"

        "📝 <b>Deskripsi</b>\n"
        f"{file['description'] or 'Belum ada deskripsi.'}"
    ).replace(",", ".")

    keyboard = []

    if file["is_paid"]:
        keyboard.append([
            InlineKeyboardButton(
                text=f"💳 Beli Rp {price:,}".replace(",", "."),
                callback_data=f"pay:{code}"
            )
        ])
        if file["free_unlock_enabled"] and int(file["free_progress"] or 0) < 3:
            keyboard.append([
                InlineKeyboardButton(
                    text=f"🎁 Buka Gratis • {int(file['free_progress'] or 0)}/3",
                    callback_data=f"freeopen:{code}"
                )
            ])
    else:
        keyboard.append([
            InlineKeyboardButton(
                text="📂 Buka File",
                callback_data=f"page:{code}:1"
            )
        ])

    keyboard.append([
        InlineKeyboardButton(
            text=f"👍 {file['likes']}",
            callback_data=f"like:{code}"
        ),
        InlineKeyboardButton(
            text=f"👎 {file['dislikes']}",
            callback_data=f"dislike:{code}"
        )
    ])

    keyboard.append([
        InlineKeyboardButton(
            text="❤️ Favorit",
            callback_data=f"favorite:{code}"
        ),
        InlineKeyboardButton(
            text="⭐ Rating",
            callback_data=f"rating:{code}"
        )
    ])

    keyboard.append([
        InlineKeyboardButton(
            text="💬 Review",
            callback_data=f"review:{code}"
        )
    ])

    keyboard.append([
        InlineKeyboardButton(
            text="📤 Bagikan",
            callback_data=f"share:{code}"
        )
    ])

    keyboard.append([
        InlineKeyboardButton(
            text="⬅️ Marketplace",
            callback_data="marketplace"
        )
    ])

    await call.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=keyboard
        )
    )


@router.callback_query(F.data.startswith("freeopen:"))
async def free_open(call: CallbackQuery):
    code = call.data.split(":", 1)[1]
    pool = await __import__("database").get_pool()
    file = await pool.fetchrow(
        """SELECT code,title,price,free_unlock_enabled
           FROM files WHERE code=$1 LIMIT 1""", code
    )
    if not file:
        return await call.answer("❌ Code tidak ditemukan.", show_alert=True)
    if not file["free_unlock_enabled"]:
        return await call.answer("❌ Buka gratis tidak tersedia untuk code ini.", show_alert=True)

    await pool.execute(
        """INSERT INTO free_code_unlocks(code,user_id,share_count,completed)
           VALUES($1,$2,0,FALSE)
           ON CONFLICT(code,user_id) DO NOTHING""",
        code, call.from_user.id
    )
    progress = await pool.fetchval(
        "SELECT share_count FROM free_code_unlocks WHERE code=$1 AND user_id=$2",
        code, call.from_user.id
    )
    progress = int(progress or 0)

    if progress >= 3:
        return await call.message.edit_text(
            "🎉 <b>CODE GRATIS TERBUKA</b>\n\n"
            f"🔑 <code>{code}</code>\n"
            "Sekarang kamu bisa membuka code ini tanpa pembayaran.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="📂 Buka Code", callback_data=f"page:{code}:1")],
                [InlineKeyboardButton(text="⬅️ Marketplace", callback_data="marketplace")]
            ])
        )

    me = await call.bot.get_me()
    share_url = share_url_for_code(me, code, file["title"] or code)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"📤 Bagikan Code • {progress}/3", url=share_url)],
        [InlineKeyboardButton(text="✅ Saya Sudah Bagikan", callback_data=f"freeshare:{code}")],
        [InlineKeyboardButton(text="⬅️ Kembali", callback_data=f"market:{code}")]
    ])
    await call.message.edit_text(
        "🎁 <b>BUKA CODE GRATIS</b>\n━━━━━━━━━━━━━━\n\n"
        "Ingin membuka code tanpa membeli?\n"
        "Bagikan code ini untuk membantu seller mendapatkan pembeli.\n\n"
        f"📈 Progress kamu: <b>{progress}/3</b>\n"
        "Setelah 3 aksi bagikan, akses gratis akan terbuka.",
        parse_mode="HTML", reply_markup=kb
    )
    await call.answer()


@router.callback_query(F.data.startswith("freeshare:"))
async def free_share(call: CallbackQuery):
    code = call.data.split(":", 1)[1]
    pool = await __import__("database").get_pool()
    file = await pool.fetchrow(
        "SELECT code,title,free_unlock_enabled FROM files WHERE code=$1", code
    )
    if not file:
        return await call.answer("❌ Code tidak ditemukan.", show_alert=True)
    if not file["free_unlock_enabled"]:
        return await call.answer("❌ Fitur gratis tidak tersedia.", show_alert=True)

    await pool.execute(
        """INSERT INTO free_code_unlocks(code,user_id,share_count,completed)
           VALUES($1,$2,1,FALSE)
           ON CONFLICT(code,user_id)
           DO UPDATE SET share_count=LEAST(3,free_code_unlocks.share_count+1)""",
        code, call.from_user.id
    )
    progress = int(await pool.fetchval(
        "SELECT share_count FROM free_code_unlocks WHERE code=$1 AND user_id=$2",
        code, call.from_user.id
    ) or 0)
    completed = progress >= 3
    await pool.execute(
        "UPDATE free_code_unlocks SET completed=$1,completed_at=CASE WHEN $1 THEN COALESCE(completed_at,NOW()) ELSE completed_at END WHERE code=$2 AND user_id=$3",
        completed, code, call.from_user.id
    )

    if completed:
        await call.answer("🎉 Progress 3/3! Code gratis terbuka.", show_alert=True)
        return await call.message.edit_text(
            "🎉 <b>CODE GRATIS AKTIF</b>\n\n"
            f"🔑 Code: <code>{code}</code>\n"
            "Sekarang kamu bisa membuka code ini tanpa pembayaran.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="📂 Buka Code", callback_data=f"page:{code}:1")],
                [InlineKeyboardButton(text="⬅️ Marketplace", callback_data="marketplace")]
            ])
        )

    me = await call.bot.get_me()
    await call.answer(f"Progress {progress}/3.", show_alert=True)
    await call.message.edit_reply_markup(
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"📤 Bagikan Code • {progress}/3", url=share_url_for_code(me, code, file["title"] or code))],
            [InlineKeyboardButton(text="✅ Saya Sudah Bagikan", callback_data=f"freeshare:{code}")],
            [InlineKeyboardButton(text="⬅️ Kembali", callback_data=f"market:{code}")]
        ])
    )


def share_url_for_code(me, code, title=""):
    
    from urllib.parse import quote
    return "https://t.me/share/url?" + f"url={quote(f'https://t.me/{me.username}?start={code}')}&text={quote('🤖 Coba code Telegram dari Marketplace!')}"
