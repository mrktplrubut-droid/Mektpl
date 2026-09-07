from aiogram import Router, F
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton
)
from database import fetchrow, fetchval, execute, get_pool
from utils.share_unlock import get_share_status, ensure_share_progress, share_url, gate_message
router = Router()
# ============================================================
# SHARE URL
# ============================================================
def share_url_for_code(me, code, title="", sharer_id=0):
    return share_url(
        me.username,
        code,
        sharer_id,
        title,
    )

# ============================================================
# MARKETPLACE DETAIL
# ============================================================
@router.callback_query(F.data.startswith("market:"))
async def market_detail(call: CallbackQuery):
    await call.answer()
    code = call.data.split(":", 1)[1].strip()
    # --------------------------------------------------------
    # LANGUAGE
    # --------------------------------------------------------
    lang = (
        await fetchval(
            """
            SELECT language
            FROM users
            WHERE user_id=$1
            """,
            call.from_user.id
        )
    ) or "id"
    # --------------------------------------------------------
    # GET FILE
    # --------------------------------------------------------
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
        WHERE code=$1
        LIMIT 1
        """,
        code
    )
    if not file:
        return await call.answer(
            "❌ File tidak ditemukan.",
            show_alert=True
        )
    # --------------------------------------------------------
    # UNIQUE VIEW
    # --------------------------------------------------------
    viewed = await fetchrow(
        """
        INSERT INTO file_views(user_id, file_code)
        VALUES($1, $2)
        ON CONFLICT (user_id, file_code)
        DO NOTHING
        RETURNING user_id
        """,
        call.from_user.id,
        code
    )
    if viewed:
        await execute(
            """
            UPDATE files
            SET
                views = COALESCE(views, 0) + 1,
                view_count = COALESCE(view_count, 0) + 1
            WHERE code=$1
            """,
            code
        )
    current_views = int(file["views"] or 0) + (
        1 if viewed else 0
    )
    price = int(file["price"] or 0)
    # --------------------------------------------------------
    # FREE PROGRESS
    # --------------------------------------------------------
    share_progress, share_target, share_completed = await get_share_status(
        await get_pool(),
        code,
        call.from_user.id,
        is_paid=bool(file["is_paid"]),
        media_count=int(file["media_count"] or 0),
    )
    # ========================================================
    # INDONESIAN
    # ========================================================
    if lang == "id":
        text = (
            "📦 <b>DETAIL FILE</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            f"📝 <b>{file['title']}</b>\n"
            f"🔑 <b>Code :</b> <code>{file['code']}</code>\n\n"
            f"📂 <b>Kategori :</b> "
            f"{file['category'] or 'Lainnya'}\n"
            f"📁 <b>Total Media :</b> "
            f"{file['media_count'] or 0}\n"
            f"💰 <b>Harga :</b> "
            f"Rp {price:,}\n"
            f"👤 <b>Seller :</b> "
            f"<code>{file['owner_id']}</code>\n\n"
            f"🔥 <b>Terjual :</b> "
            f"{file['sold']}\n"
            f"👁 <b>Dilihat :</b> "
            f"{current_views}\n"
            f"❤️ <b>Suka :</b> "
            f"{file['likes']}  |  "
            f"👎 <b>Tidak suka :</b> "
            f"{file['dislikes']}\n"
            f"❤️ <b>Favorit :</b> "
            f"{file['favorite_count']}\n"
            f"⭐ <b>Rating :</b> "
            f"{float(file['rating'] or 0):.1f} "
            f"({file['review_count']} Review)\n\n"
            "📝 <b>Deskripsi</b>\n"
            f"{file['description'] or 'Belum ada deskripsi.'}"
        ).replace(",", ".")
    # ========================================================
    # ENGLISH
    # ========================================================
    else:
        text = (
            "📦 <b>CODE DETAILS</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            f"📝 <b>{file['title']}</b>\n"
            f"🔑 <b>Code:</b> "
            f"<code>{file['code']}</code>\n\n"
            f"📂 <b>Category:</b> "
            f"{file['category'] or 'Other'}\n"
            f"📁 <b>Total Media:</b> "
            f"{file['media_count'] or 0}\n"
            f"💰 <b>Price:</b> "
            f"Rp {price:,}\n"
            f"👤 <b>Seller:</b> "
            f"<code>{file['owner_id']}</code>\n\n"
            f"🔥 <b>Sold:</b> "
            f"{file['sold']}\n"
            f"👁 <b>Views:</b> "
            f"{current_views}\n"
            f"❤️ <b>Likes:</b> "
            f"{file['likes']}  |  "
            f"👎 <b>Dislikes:</b> "
            f"{file['dislikes']}\n"
            f"❤️ <b>Favorites:</b> "
            f"{file['favorite_count']}\n"
            f"⭐ <b>Rating:</b> "
            f"{float(file['rating'] or 0):.1f} "
            f"({file['review_count']} reviews)\n\n"
            "📝 <b>Description</b>\n"
            f"{file['description'] or 'No description yet.'}"
        ).replace(",", ".")
    # ========================================================
    # KEYBOARD
    # ========================================================
    keyboard = []
    # --------------------------------------------------------
    # PAID / FREE
    # --------------------------------------------------------
    if file["is_paid"]:
        keyboard.append([
            InlineKeyboardButton(
                text=(
                    f"💳 Beli Rp {price:,}"
                    if lang == "id"
                    else f"💳 Buy Rp {price:,}"
                ).replace(",", "."),
                callback_data=f"pay:{code}"
            )
        ])
        if (file["is_paid"] or file["free_unlock_enabled"]) and not share_completed:
            keyboard.append([
                InlineKeyboardButton(
                    text=(
                        f"🎁 Buka Gratis • "
                        f"{share_progress}/{share_target}"
                    ),
                    callback_data=f"freeopen:{code}"
                )
            ])
    else:
        keyboard.append([
            InlineKeyboardButton(
                text=(
                    "📂 Buka File"
                    if lang == "id"
                    else "📂 Open File"
                ),
                callback_data=f"page:{code}:1"
            )
        ])
    # --------------------------------------------------------
    # LIKE / DISLIKE
    # --------------------------------------------------------
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
    # --------------------------------------------------------
    # FAVORITE / RATING
    # --------------------------------------------------------
    keyboard.append([
        InlineKeyboardButton(
            text=(
                "❤️ Favorit"
                if lang == "id"
                else "❤️ Favorite"
            ),
            callback_data=f"favorite:{code}"
        ),
        InlineKeyboardButton(
            text="⭐ Rating",
            callback_data=f"rating:{code}"
        )
    ])
    # --------------------------------------------------------
    # REVIEW
    # --------------------------------------------------------
    keyboard.append([
        InlineKeyboardButton(
            text=(
                "💬 Review"
                if lang == "id"
                else "💬 Review"
            ),
            callback_data=f"review:{code}"
        )
    ])
    # --------------------------------------------------------
    # SHARE
    # --------------------------------------------------------
    keyboard.append([
        InlineKeyboardButton(
            text=(
                "📤 Bagikan"
                if lang == "id"
                else "📤 Share"
            ),
            callback_data=f"share:{code}"
        )
    ])
    # --------------------------------------------------------
    # BACK
    # --------------------------------------------------------
    keyboard.append([
        InlineKeyboardButton(
            text="⬅️ Marketplace",
            callback_data="marketplace"
        )
    ])
    # --------------------------------------------------------
    # SEND DETAIL
    # --------------------------------------------------------
    await call.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=keyboard
        )
    )
# ============================================================
# FREE OPEN
# ============================================================
@router.callback_query(F.data.startswith("freeopen:"))
async def free_open(call: CallbackQuery):
    code = call.data.split(":", 1)[1].strip()
    pool = await get_pool()
    file = await pool.fetchrow(
        """
        SELECT
            code,
            title,
            price,
            media_count,
            is_paid,
            free_unlock_enabled
        FROM files
        WHERE code=$1
        LIMIT 1
        """,
        code
    )
    if not file:
        return await call.answer(
            "❌ Code tidak ditemukan.",
            show_alert=True
        )
    if not file["free_unlock_enabled"] and not file["is_paid"]:
        return await call.answer(
            "❌ Unlock share tidak tersedia untuk code ini.",
            show_alert=True
        )
    # --------------------------------------------------------
    # SHARE PROGRESS
    # --------------------------------------------------------
    progress, target, completed = await get_share_status(
        pool, code, call.from_user.id,
        is_paid=bool(file["is_paid"]),
        media_count=int(file["media_count"] or 0),
    )
    await ensure_share_progress(
        pool, code, call.from_user.id,
        is_paid=bool(file["is_paid"]),
        media_count=int(file["media_count"] or 0),
    )

    # ========================================================
    # ALREADY UNLOCKED
    # ========================================================
    if completed or progress >= target:
        await call.answer()
        return await call.message.edit_text(
            "🎉 <b>CODE GRATIS TERBUKA</b>\n\n"
            f"🔑 <code>{code}</code>\n\n"
            "Sekarang kamu bisa membuka code ini "
            "tanpa pembayaran.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="📂 Buka Code",
                            callback_data=f"page:{code}:1"
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            text="⬅️ Marketplace",
                            callback_data="marketplace"
                        )
                    ]
                ]
            )
        )
    # --------------------------------------------------------
    # SHARE
    # --------------------------------------------------------
    me = await call.bot.get_me()
    share_url = share_url_for_code(
        me,
        code,
        file["title"] or code,
        call.from_user.id,
    )
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"📤 Bagikan Code • {progress}/{target}",
                    url=share_url
                )
            ],
            [
                InlineKeyboardButton(
                    text="✅ Saya Sudah Bagikan",
                    callback_data=f"freeshare:{code}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="⬅️ Kembali",
                    callback_data=f"market:{code}"
                )
            ]
        ]
    )
    await call.message.edit_text(
        "🎁 <b>BUKA CODE GRATIS</b>\n"
        "━━━━━━━━━━━━━━\n\n"
        "Ingin membuka code tanpa membeli?\n"
        "Bagikan code ini untuk membantu seller "
        "mendapatkan pembeli.\n\n"
        f"🔑 <b>Code:</b> <code>{code}</code>\n\n"
        f"📈 Progress kamu: "
        f"<b>{progress}/{target}</b>\n\n"
        "Setelah target tercapai, akses akan terbuka.",
        parse_mode="HTML",
        reply_markup=kb
    )
    await call.answer()
# ============================================================
# FREE SHARE / CHECK PROGRESS
# ============================================================
@router.callback_query(F.data.startswith(("freeshare:", "sharecheck:")))
async def free_share(call: CallbackQuery):
    code = call.data.split(":", 1)[1].strip()
    pool = await get_pool()

    file = await fetchrow(
        """
        SELECT code,title,media_count,is_paid,free_unlock_enabled
        FROM files WHERE code=$1 LIMIT 1
        """,
        code,
    )
    if not file:
        return await call.answer("❌ Code tidak ditemukan.", show_alert=True)

    if not file["free_unlock_enabled"]:
        return await call.answer("❌ Fitur unlock tidak tersedia.", show_alert=True)

    progress, target, completed = await get_share_status(
        pool, code, call.from_user.id,
        is_paid=bool(file["is_paid"]),
        media_count=int(file["media_count"] or 0),
    )
    await ensure_share_progress(
        pool, code, call.from_user.id,
        is_paid=bool(file["is_paid"]),
        media_count=int(file["media_count"] or 0),
    )

    if completed or progress >= target:
        return await call.message.edit_text(
            "🎉 <b>CODE TERBUKA</b>\n\n"
            f"🔑 <code>{code}</code>\n"
            f"📈 Progress: <b>{target}/{target}</b>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="📂 Buka Code", callback_data=f"page:{code}:1")],
                [InlineKeyboardButton(text="📤 Open All", callback_data=f"all:{code}")],
                [InlineKeyboardButton(text="⬅️ Marketplace", callback_data="marketplace")],
            ]),
        )

    me = await call.bot.get_me()
    url = share_url_for_code(
        me, code, file["title"] or code, call.from_user.id
    )
    label = "PAID" if file["is_paid"] else "FREE"
    await call.message.edit_text(
        f"🔐 <b>UNLOCK {label}</b>\n\n"
        "Bagikan code ini. Progress bertambah hanya saat "
        "member baru benar-benar membuka bot melalui link share.\n\n"
        f"📈 Progress: <b>{progress}/{target}</b>\n"
        f"👥 Target: <b>{target} member baru</b>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"📤 Bagikan Code • {progress}/{target}", url=url)],
            [InlineKeyboardButton(text="🔄 Cek Progress", callback_data=f"sharecheck:{code}")],
            [InlineKeyboardButton(text="⬅️ Kembali", callback_data=f"market:{code}")],
        ]),
    )
    await call.answer("🔄 Progress diperbarui.")
