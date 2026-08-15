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


# =========================================================
# CEK KREATOR TERVERIFIKASI
# =========================================================

def creator_verified(user) -> bool:

    if not user:
        return False

    return (
        bool(user["is_creator"])
        and user["creator_status"] == "approved"
    )


# =========================================================
# /START
# =========================================================

@router.message(CommandStart())
async def start_cmd(
    message: Message,
    state: FSMContext
):

    await state.clear()

    user_id = message.from_user.id

    username = (
        f"@{message.from_user.username}"
        if message.from_user.username
        else message.from_user.full_name
    )

    loading = await message.answer(
        "⚡ Loading..."
    )

    try:

        await process_start(
            message,
            loading,
            user_id,
            username
        )

    except Exception as e:

        logging.exception(
            f"START ERROR: {e}"
        )

        try:

            await loading.edit_text(
                "❌ <b>SYSTEM ERROR</b>\n\n"
                "Terjadi kesalahan saat membuka bot.",
                parse_mode="HTML"
            )

        except Exception:
            pass


# =========================================================
# PROCESS START
# =========================================================

async def process_start(
    message: Message,
    loading: Message,
    user_id: int,
    username: str
):

    bot = message.bot

    # =====================================================
    # FORCE SUB
    # =====================================================

    try:

        subscribed = await check_force_sub(
            bot,
            user_id
        )

    except Exception:

        logging.exception(
            "FORCE SUB CHECK ERROR"
        )

        # Jangan membuat bot mati jika force-sub error
        subscribed = True

    if not subscribed:

        try:

            bot_username = (
                await bot.me()
            ).username

        except Exception:

            bot_username = None

        await loading.edit_text(
            "❌ <b>JOIN REQUIRED</b>\n\n"
            "Silakan join semua channel terlebih dahulu.",

            reply_markup=join_kb(
                bot_username,
                user_id
            ),

            parse_mode="HTML"
        )

        return

    # =====================================================
    # DATABASE
    # =====================================================

    pool = await get_pool()

    # =====================================================
    # CEK USER BARU
    # =====================================================

    existing_user = await pool.fetchval(
        """
        SELECT 1
        FROM users
        WHERE user_id = $1
        """,
        user_id
    )

    is_new_user = existing_user is None

    # =====================================================
    # INSERT / UPDATE USER
    # =====================================================

    await pool.execute(
        """
        INSERT INTO users(
            user_id,
            username,
            fullname,
            chat_id,
            last_seen
        )
        VALUES(
            $1,
            $2,
            $3,
            $1,
            NOW()
        )

        ON CONFLICT(user_id)
        DO UPDATE SET
            username = EXCLUDED.username,
            fullname = EXCLUDED.fullname,
            chat_id = EXCLUDED.chat_id,
            last_seen = NOW()
        """,

        user_id,
        username,
        message.from_user.full_name
    )

    # =====================================================
    # AMBIL PARAMETER /START
    # =====================================================

    args = message.text.split(
        maxsplit=1
    )

    # =====================================================
    # REFERRAL
    #
    # /start ref_123456
    # =====================================================

    if (
        len(args) > 1
        and args[1].startswith("ref_")
    ):

        if is_new_user:

            ref_id_text = args[1].replace(
                "ref_",
                "",
                1
            )

            if ref_id_text.isdigit():

                ref_id = int(
                    ref_id_text
                )

                # Tidak boleh referral diri sendiri
                if ref_id != user_id:

                    # Pastikan referral user ada
                    ref_exists = await pool.fetchval(
                        """
                        SELECT 1
                        FROM users
                        WHERE user_id = $1
                        """,
                        ref_id
                    )

                    if ref_exists:

                        # Cek apakah sudah punya referral
                        existing_referral = await pool.fetchval(
                            """
                            SELECT referred_by
                            FROM users
                            WHERE user_id = $1
                            """,
                            user_id
                        )

                        if not existing_referral:

                            # Simpan pemilik referral
                            await pool.execute(
                                """
                                UPDATE users
                                SET referred_by = $1
                                WHERE user_id = $2
                                """,
                                ref_id,
                                user_id
                            )

                            # Tambahkan bonus referral
                            await pool.execute(
                                """
                                UPDATE users
                                SET
                                    total_referral =
                                        COALESCE(total_referral, 0) + 1,

                                    balance =
                                        COALESCE(balance, 0) + 200

                                WHERE user_id = $1
                                """,
                                ref_id
                            )

                            # Notifikasi pemilik referral
                            try:

                                await bot.send_message(
                                    ref_id,

                                    "🎉 <b>Referral Berhasil!</b>\n\n"
                                    "👤 Pengguna baru bergabung.\n"
                                    "💰 Bonus: <b>Rp200</b>\n\n"
                                    "Saldo otomatis bertambah.",

                                    parse_mode="HTML"
                                )

                            except Exception:

                                logging.exception(
                                    "REFERRAL NOTIFICATION ERROR"
                                )

    # =====================================================
    # /START DENGAN CODE
    #
    # Contoh:
    # /start abc123
    # =====================================================

    elif len(args) > 1:

        code = args[1].strip()

        if not code:

            return await render_home_fast(
                bot,
                loading,
                user_id,
                username
            )

        # Hapus loading
        try:

            await loading.delete()

        except Exception:
            pass

        # Import setelah diperlukan
        from handlers.getfile import process_code

        return await process_code(
            message,
            code
        )

    # =====================================================
    # HOME
    # =====================================================

    user = await pool.fetchrow(
        """
        SELECT
            username,
            fullname,
            balance,
            total_referral,
            is_creator,
            creator_status
        FROM users
        WHERE user_id = $1
        """,
        user_id
    )

    display_username = (
        user["username"]
        if user and user["username"]
        else username
    )

    await render_home_fast(
        bot,
        loading,
        user_id,
        display_username
    )


# =========================================================
# RENDER HOME
# =========================================================

async def render_home_fast(
    bot,
    message,
    user_id: int,
    username: str
):

    pool = await get_pool()

    # =====================================================
    # BOT USERNAME
    # =====================================================

    try:

        bot_username = (
            await bot.me()
        ).username

    except Exception:

        bot_username = None

    # =====================================================
    # REFERRAL LINK
    # =====================================================

    if bot_username:

        ref_link = (
            f"https://t.me/"
            f"{bot_username}"
            f"?start=ref_{user_id}"
        )

    else:

        ref_link = "-"

    # =====================================================
    # USER DATA
    # =====================================================

    user = await pool.fetchrow(
        """
        SELECT
            balance,
            total_referral,
            is_creator,
            creator_status
        FROM users
        WHERE user_id = $1
        """,
        user_id
    )

    if user:

        balance = (
            user["balance"] or 0
        )

        referral = (
            user["total_referral"] or 0
        )

        is_creator = creator_verified(
            user
        )

    else:

        balance = 0
        referral = 0
        is_creator = False

    # =====================================================
    # STATUS KREATOR
    # =====================================================

    if is_creator:

        creator_text = (
            "🎨 Kreator : "
            "<b>TERVERIFIKASI ✅</b>"
        )

        balance_text = (
            f"<b>Rp {balance:,.0f}</b>"
        )

    else:

        creator_text = (
            "👤 Kreator : "
            "<b>BELUM TERVERIFIKASI 🔒</b>"
        )

        balance_text = (
            "<b>🔒 SALDO TERKUNCI</b>"
        )

    # =====================================================
    # HOME TEXT
    # =====================================================

    text = (
        "<b>✨ BOT MARKET ✨</b>\n\n"

        f"ID : <code>{user_id}</code>\n"

        f"{creator_text}\n"

        f"Saldo : {balance_text}\n"

        f"Referral : "
        f"<b>{referral}</b>\n"

        "━━━━━━━━━━━━━━\n"

        "🔗 Link Referral :\n"

        f"<code>{ref_link}</code>"
    )

    # =====================================================
    # EDIT LOADING
    # =====================================================

    try:

        await message.edit_text(
            text,
            parse_mode="HTML",
            reply_markup=home_kb(user_id),
            disable_web_page_preview=True
        )

    except TelegramBadRequest as e:

        if "message is not modified" in str(e).lower():
            return

        raise

    except Exception:

        try:

            await bot.send_message(
                user_id,
                text,
                parse_mode="HTML",
                reply_markup=home_kb(user_id),
                disable_web_page_preview=True
            )

        except Exception:

            logging.exception(
                "RENDER HOME ERROR"
            )


# =========================================================
# HOME BUTTON
# =========================================================

@router.callback_query(
    F.data == "home"
)
async def back_home(
    call: CallbackQuery,
    state: FSMContext
):

    await state.clear()

    user_id = call.from_user.id

    # =====================================================
    # FORCE SUB
    # =====================================================

    try:

        subscribed = await check_force_sub(
            call.bot,
            user_id
        )

    except Exception:

        logging.exception(
            "HOME FORCE SUB ERROR"
        )

        subscribed = True

    if not subscribed:

        try:

            bot_username = (
                await call.bot.me()
            ).username

        except Exception:

            bot_username = None

        await call.message.answer(
            "❌ <b>JOIN REQUIRED</b>\n\n"
            "Silakan join semua channel terlebih dahulu.",

            parse_mode="HTML",

            reply_markup=join_kb(
                bot_username,
                user_id
            )
        )

        return await call.answer()

    # =====================================================
    # USER
    # =====================================================

    pool = await get_pool()

    user = await pool.fetchrow(
        """
        SELECT
            username,
            fullname
        FROM users
        WHERE user_id = $1
        """,
        user_id
    )

    if user:

        username = (
            user["username"]
            or user["fullname"]
            or "unknown"
        )

    else:

        username = "unknown"

    # =====================================================
    # RENDER HOME
    # =====================================================

    await render_home_fast(
        call.bot,
        call.message,
        user_id,
        username
    )

    await call.answer()
