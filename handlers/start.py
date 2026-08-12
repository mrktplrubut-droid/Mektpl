import logging

from aiogram import Router, F
from aiogram.filters import CommandStart
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.exceptions import TelegramBadRequest

from utils.force_sub import check_force_sub
from keyboards.menu import home_kb
from keyboards.join import join_kb
from database import get_pool


router = Router()


@router.message(CommandStart())
async def start_cmd(message: Message, state: FSMContext):
    await state.clear()

    user_id = message.from_user.id
    username = (
        f"@{message.from_user.username}"
        if message.from_user.username
        else message.from_user.full_name
    )

    loading = await message.answer("⚡ Loading...")

    try:
        await process_start(message, loading, user_id, username)
    except Exception as e:
        logging.exception(f"START ERROR: {e}")
        try:
            await loading.edit_text("❌ SYSTEM ERROR")
        except:
            pass


async def process_start(message, loading, user_id, username):
    bot = message.bot

    try:
        sub = await check_force_sub(bot, user_id)
    except Exception:
        sub = True

    if not sub:
        bot_username = (await bot.me()).username

        await loading.edit_text(
            "❌ <b>JOIN REQUIRED</b>\n\n"
            "Silakan join semua channel terlebih dahulu.",
            reply_markup=join_kb(bot_username, user_id),
            parse_mode="HTML"
        )
        return

    pool = await get_pool()

    is_new_user = not await pool.fetchval(
        "SELECT 1 FROM users WHERE user_id=$1",
        user_id
    )

    await pool.execute(
        """
        INSERT INTO users(
            user_id,
            username,
            fullname
        )
        VALUES($1,$2,$3)

        ON CONFLICT(user_id)
        DO UPDATE SET
            username = EXCLUDED.username,
            fullname = EXCLUDED.fullname
        """,
        user_id,
        username,
        message.from_user.full_name
    )

    args = message.text.split(maxsplit=1)

    # =========================
    # REFERRAL
    # =========================
    if len(args) > 1 and args[1].startswith("ref_"):

        if is_new_user:

            ref_id = args[1].replace("ref_", "", 1)

            if ref_id.isdigit():

                ref_id = int(ref_id)

                if ref_id != user_id:

                    existing = await pool.fetchval(
                        "SELECT referred_by FROM users WHERE user_id=$1",
                        user_id
                    )

                    if not existing:

                        await pool.execute(
                            """
                            UPDATE users
                            SET referred_by=$1
                            WHERE user_id=$2
                            """,
                            ref_id,
                            user_id
                        )

                        await pool.execute(
                            """
                            UPDATE users
                            SET
                                total_referral = total_referral + 1,
                                balance = balance + 200
                            WHERE user_id=$1
                            """,
                            ref_id
                        )

                        try:
                            await bot.send_message(
                                ref_id,
                                "🎉 <b>Referral Berhasil!</b>\n\n"
                                "👤 Pengguna baru bergabung.\n"
                                "💰 Bonus: <b>Rp200</b>\n\n"
                                "Saldo otomatis bertambah.",
                                parse_mode="HTML"
                            )
                        except:
                            pass

    # =========================
    # START DENGAN KODE
    # =========================
    elif len(args) > 1:

        code = args[1].strip()

        try:
            await loading.delete()
        except:
            pass

        from handlers.getfile import process_code

        return await process_code(message, code)

    user = await pool.fetchrow(
        "SELECT username FROM users WHERE user_id=$1",
        user_id
    )

    await render_home_fast(
        bot,
        loading,
        user_id,
        user["username"] or "unknown"
    )


async def render_home_fast(bot, message, user_id, username):

    pool = await get_pool()

    bot_username = (await bot.me()).username
    ref_link = f"https://t.me/{bot_username}?start=ref_{user_id}"

    balance = await pool.fetchval(
        "SELECT balance FROM users WHERE user_id=$1",
        user_id
    ) or 0

    referral = await pool.fetchval(
        "SELECT total_referral FROM users WHERE user_id=$1",
        user_id
    ) or 0

    text = f"""
<b>✨ BOT MARKET ✨</b>

ID : <code>{user_id}</code>
Saldo : <b>Rp {balance:,.0f}</b>
Referral : <b>{referral}</b>
━━━━━━━━━━━━━━
🔗 Link Referral :
<code>{ref_link}</code>
"""

    try:
        await message.edit_text(
            text,
            parse_mode="HTML",
            reply_markup=home_kb(user_id),
            disable_web_page_preview=True
        )

    except TelegramBadRequest as e:
        if "message is not modified" in str(e):
            return
        raise

    except:
        await bot.send_message(
            user_id,
            text,
            parse_mode="HTML",
            reply_markup=home_kb(user_id),
            disable_web_page_preview=True
        )


@router.callback_query(F.data == "home")
async def back_home(call: CallbackQuery, state: FSMContext):

    await state.clear()

    user_id = call.from_user.id

    try:
        ok = await check_force_sub(call.bot, user_id)
    except:
        ok = True

    if not ok:

        bot_username = (await call.bot.me()).username

        await call.message.answer(
            "❌ <b>JOIN REQUIRED</b>\n\n"
            "Silakan join semua channel terlebih dahulu.",
            parse_mode="HTML",
            reply_markup=join_kb(bot_username, user_id)
        )

        return await call.answer()

    pool = await get_pool()

    user = await pool.fetchrow(
        "SELECT username FROM users WHERE user_id=$1",
        user_id
    )

    await render_home_fast(
        call.bot,
        call.message,
        user_id,
        user["username"] or "unknown"
    )

    await call.answer()
