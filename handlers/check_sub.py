import logging

from aiogram import Router, F
from aiogram.types import CallbackQuery
from aiogram.exceptions import TelegramBadRequest

from utils.force_sub import check_force_sub
from keyboards.join import join_kb
from handlers.start import render_home_fast
from database import get_pool

router = Router()


# =========================================================
# CHECK SUB
# =========================================================

@router.callback_query(F.data == "check_sub")
async def check_sub_callback(call: CallbackQuery):

    user_id = call.from_user.id

    username = (
        f"@{call.from_user.username}"
        if call.from_user.username
        else call.from_user.full_name
    )

    logging.info(
        f"CHECK SUB CLICKED: {user_id}"
    )

    # =====================================================
    # CEK FORCE SUB
    # =====================================================

    try:

        ok = await check_force_sub(
            call.bot,
            user_id
        )

        logging.info(
            f"FORCE SUB RESULT: {ok}"
        )

    except Exception:

        logging.exception(
            "FORCE SUB CHECK ERROR"
        )

        return await call.answer(
            "❌ Gagal mengecek membership.",
            show_alert=True
        )

    # =====================================================
    # BELUM JOIN
    # =====================================================

    if not ok:

        await call.answer(
            "❌ Kamu belum join semua channel.",
            show_alert=True
        )

        try:

            await call.message.edit_text(
                (
                    "❌ <b>JOIN REQUIRED</b>\n\n"
                    "Silakan join semua channel terlebih dahulu.\n\n"
                    "Setelah selesai, tekan tombol "
                    "<b>✅ CHECK</b>."
                ),
                parse_mode="HTML",
                reply_markup=join_kb()
            )

        except TelegramBadRequest as e:

            if "message is not modified" not in str(e).lower():
                logging.exception(
                    "JOIN MESSAGE EDIT ERROR"
                )

        return

    # =====================================================
    # SUDAH JOIN
    # =====================================================

    pool = await get_pool()

    # =====================================================
    # CREATE / UPDATE USER
    # =====================================================

    try:

        await pool.execute(
            """
            INSERT INTO users (
                user_id,
                username,
                fullname,
                chat_id,
                last_seen
            )
            VALUES (
                $1,
                $2,
                $3,
                $1,
                NOW()
            )

            ON CONFLICT (user_id)
            DO UPDATE SET
                username = EXCLUDED.username,
                fullname = EXCLUDED.fullname,
                chat_id = EXCLUDED.chat_id,
                last_seen = NOW()
            """,

            user_id,
            username,
            call.from_user.full_name
        )

    except Exception:

        logging.exception(
            "CREATE / UPDATE USER ERROR"
        )

        return await call.answer(
            "❌ Gagal memperbarui data user.",
            show_alert=True
        )

    # =====================================================
    # VERIFIKASI BERHASIL
    # =====================================================

    await call.answer(
        "✅ Verifikasi berhasil!"
    )

    # =====================================================
    # LANGSUNG TAMPILKAN HOME
    #
    # Pesan JOIN akan diedit menjadi HOME.
    # Jadi tombol JOIN / CHECK otomatis hilang.
    # =====================================================

    try:

        await render_home_fast(
            call.bot,
            call.message,
            user_id,
            username
        )

    except TelegramBadRequest as e:

        if "message is not modified" not in str(e).lower():

            logging.exception(
                "RENDER HOME AFTER JOIN ERROR"
            )

            try:

                await call.message.answer(
                    "🏠 <b>HOME</b>",
                    parse_mode="HTML"
                )

            except Exception:
                pass

    except Exception:

        logging.exception(
            "RENDER HOME AFTER JOIN ERROR"
        )

        try:

            await call.message.answer(
                "🏠 <b>HOME</b>",
                parse_mode="HTML"
            )

        except Exception:
            pass
