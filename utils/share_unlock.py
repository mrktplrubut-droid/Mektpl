"""Share-to-unlock system.

A progress point is awarded only when a genuinely new bot member opens a
code through that code's generated share/deep link.  Events are unique per
(code, owner, new_member), so refreshes/retries cannot inflate progress.
"""
from __future__ import annotations

import math
from urllib.parse import quote

from database import get_pool


def required_shares(is_paid: bool, media_count: int) -> int:
    if is_paid:
        return 10
    return max(1, math.ceil(max(1, int(media_count or 1)) / 5))


def share_payload(code: str, sharer_id: int) -> str:
    return f"s_{code}_{int(sharer_id)}"


def share_url(bot_username: str, code: str, sharer_id: int, title: str = "") -> str:
    username = (bot_username or "").lstrip("@")
    deep = f"https://t.me/{username}?start={share_payload(code, sharer_id)}"
    text = (
        f"📦 {title or 'Code Telegram'}\n\n"
        "Buka lewat bot untuk melihat code ini."
    )
    return f"https://t.me/share/url?url={quote(deep)}&text={quote(text)}"


async def get_share_status(pool, code: str, user_id: int, *, is_paid: bool, media_count: int):
    target = required_shares(is_paid, media_count)
    row = await pool.fetchrow(
        """
        SELECT progress, completed
        FROM code_share_progress
        WHERE code=$1 AND user_id=$2
        """,
        code, user_id
    )
    current = int(row["progress"] or 0) if row else 0
    completed = bool(row["completed"]) if row else current >= target
    return current, target, completed


async def ensure_share_progress(pool, code: str, user_id: int, *, is_paid: bool, media_count: int):
    target = required_shares(is_paid, media_count)
    await pool.execute(
        """
        INSERT INTO code_share_progress(code,user_id,target,is_paid)
        VALUES($1,$2,$3,$4)
        ON CONFLICT(code,user_id)
        DO UPDATE SET target=EXCLUDED.target, is_paid=EXCLUDED.is_paid
        """,
        code, user_id, target, bool(is_paid)
    )


async def record_new_member_open(
    pool,
    code: str,
    owner_id: int,
    new_member_id: int,
    *,
    media_count: int,
    is_paid: bool,
) -> bool:
    """Award exactly one point when a new Telegram user opens a shared code."""
    if int(owner_id) == int(new_member_id):
        return False

    await ensure_share_progress(
        pool, code, owner_id,
        is_paid=is_paid, media_count=media_count
    )

    inserted = await pool.fetchval(
        """
        INSERT INTO code_share_events(code,owner_id,new_member_id)
        VALUES($1,$2,$3)
        ON CONFLICT(code,owner_id,new_member_id) DO NOTHING
        RETURNING id
        """,
        code, owner_id, new_member_id
    )
    if not inserted:
        return False

    await pool.execute(
        """
        UPDATE code_share_progress
        SET
            progress=LEAST(target, COALESCE(progress,0)+1),
            completed=(LEAST(target, COALESCE(progress,0)+1) >= target),
            completed_at=CASE
                WHEN LEAST(target, COALESCE(progress,0)+1) >= target
                THEN COALESCE(completed_at,NOW())
                ELSE completed_at
            END,
            updated_at=NOW()
        WHERE code=$1 AND user_id=$2
        """,
        code, owner_id
    )
    return True


async def gate_message(
    bot,
    chat_id: int,
    *,
    code: str,
    title: str,
    progress: int,
    target: int,
    is_paid: bool,
):
    me = await bot.get_me()
    url = share_url(me.username, code, chat_id, title)

    mode = "PAID" if is_paid else "FREE"
    text = (
        f"🔐 <b>UNLOCK {mode}</b>\n"
        "━━━━━━━━━━━━━━\n\n"
        "Sebelum code dibuka, bagikan code ini terlebih dahulu.\n\n"
        f"📈 Progress: <b>{progress}/{target}</b>\n"
        f"👥 Dibutuhkan: <b>{target} member baru</b>\n\n"
        "Progress hanya bertambah jika orang baru membuka bot "
        "melalui link share ini. User lama, refresh, atau klik berulang "
        "tidak dihitung."
    )
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    return text, InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"📤 Bagikan Code • {progress}/{target}", url=url)],
        [InlineKeyboardButton(text="🔄 Cek Progress", callback_data=f"sharecheck:{code}")],
        [InlineKeyboardButton(text="⬅️ Kembali", callback_data=f"market:{code}")]
    ])


async def telegram_setting(key: str, default: float) -> float:
    """Read a numeric safety setting; falls back safely when DB is unavailable."""
    try:
        pool = await get_pool()
        value = await pool.fetchval("SELECT value FROM settings WHERE key=$1", key)
        return max(0.0, float(value)) if value is not None else float(default)
    except Exception:
        return float(default)
