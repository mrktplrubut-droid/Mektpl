import logging

from aiogram import Router, F
from aiogram.types import CallbackQuery
from aiogram.exceptions import TelegramBadRequest

from utils.force_sub import check_force_sub
from keyboards.join import join_kb
from handlers.start import render_home_fast
from database import get_pool
from utils.user import get_user_status

router = Router()


@router.callback_query(F.data == "check_sub")
async def check_sub_callback(call: CallbackQuery):

    user_id = call.from_user.id
    username = call.from_user.username or "unknown"

    logging.info(f"CHECK SUB CLICKED: {user_id}")

    try:

        ok = await check_force_sub(call.bot, user_id)

        logging.info(f"FORCE SUB RESULT: {ok}")

        if not ok:

            await call.answer(
                "❌ Kamu belum join semua channel.",
                show_alert=True
            )

            try:
                await call.message.edit_text(
                    "❌ Kamu belum join semua channel.\n\n"
                    "Silakan join dulu lalu klik CHECK lagi.",
                    reply_markup=join_kb()
                )
            except TelegramBadRequest as e:
                if "message is not modified" not in str(e):
                    raise

            return


        pool = await get_pool()


        # =========================
        # CREATE / UPDATE USER
        # =========================
        await pool.execute(
            """
            INSERT INTO users (
                user_id,
                chat_id,
                username,
                full_name,
                balance
            )
            VALUES ($1, $1, $2, $3, 0)

            ON CONFLICT (user_id)
            DO UPDATE SET
                username = EXCLUDED.username,
                full_name = EXCLUDED.full_name
            """,
            user_id,
            username,
            call.from_user.full_name
        )


        # =========================
        # FETCH USER
        # =========================
        user = await pool.fetchrow(
            """
            SELECT username
            FROM users
            WHERE user_id=$1
            """,
            user_id
        )


        if not user:

            logging.warning(
                f"USER STILL NULL: {user_id}"
            )

            await render_home_fast(
                call.bot,
                call.message,
                user_id,
                username,
                "free"
            )

            return


        status = await get_user_status(
            pool,
            user_id
        )


        await call.answer(
            "✅ Verifikasi berhasil"
        )


        await render_home_fast(
            call.bot,
            call.message,
            user_id,
            user["username"] or username,
            status
        )


    except Exception as e:

        logging.exception(
            f"CHECK SUB ERROR: {e}"
        )

        await call.answer(
            "❌ SYSTEM ERROR",
            show_alert=True
        )
