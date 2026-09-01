import logging

from aiogram import Router, F
from aiogram.filters import CommandStart
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.exceptions import TelegramBadRequest

from utils.force_sub import check_force_sub
from keyboards.menu import home_kb
from keyboards.join import join_kb
from database import get_pool
from utils.user_lang import get_user_language
from utils.force_sub import get_missing_channels
from aiogram.utils.keyboard import InlineKeyboardBuilder


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
    # SAVE / UPDATE MEMBER PADA SETIAP /START
    # =====================================================
    # Member tetap dicatat walaupun force-sub belum terpenuhi.
    # Ini membuat daftar member/admin selalu terisi.
    pool = await get_pool()

    existing_user = await pool.fetchval(
        "SELECT 1 FROM users WHERE user_id=$1",
        user_id
    )
    is_new_user = existing_user is None

    await pool.execute(
        """
        INSERT INTO users(
            user_id,
            chat_id,
            username,
            full_name,
            fullname,
            language,
            last_seen
        )
        VALUES($1, $1, $2, $3, $3, NULL, NOW())
        ON CONFLICT(user_id)
        DO UPDATE SET
            chat_id = EXCLUDED.chat_id,
            username = EXCLUDED.username,
            full_name = EXCLUDED.full_name,
            fullname = EXCLUDED.fullname,
            last_seen = NOW()
        """,
        user_id,
        message.from_user.username,
        message.from_user.full_name
    )

    # First /start: choose language before anything else.
    current_lang = await pool.fetchval(
        "SELECT language FROM users WHERE user_id=$1",
        user_id
    )
    if not current_lang:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="🇮🇩 Indonesia", callback_data="lang:id"),
                InlineKeyboardButton(text="🇬🇧 English", callback_data="lang:en"),
            ]
        ])
        # Keep referral attribution even while language is being selected.
        raw = message.text.split(maxsplit=1)[1] if len(message.text.split(maxsplit=1)) > 1 else ""
        if raw.startswith("ref_") and raw[4:].isdigit() and int(raw[4:]) != user_id:
            ref_id = int(raw[4:])
            ref_exists = await pool.fetchval("SELECT 1 FROM users WHERE user_id=$1", ref_id)
            if ref_exists:
                await pool.execute("UPDATE users SET referred_by=$1 WHERE user_id=$2 AND referred_by IS NULL", ref_id, user_id)
                await pool.execute(
                    "UPDATE users SET referral_count=COALESCE(referral_count,0)+1,total_referral=COALESCE(total_referral,0)+1,balance=COALESCE(balance,0)+200,updated_at=NOW() WHERE user_id=$1",
                    ref_id
                )
                try:
                    from utils.referral import check_referral_reward
                    reward = await check_referral_reward(pool, ref_id)
                    if reward:
                        await bot.send_message(ref_id, f"🎁 <b>Referral Reward</b>\n\n{reward}", parse_mode="HTML")
                except Exception:
                    logging.exception("REFERRAL REWARD ERROR")
        await loading.edit_text(
            "🌐 <b>Pilih Bahasa / Choose Language</b>\n\n"
            "🇮🇩 Pilih Bahasa Indonesia\n🇬🇧 Choose English",
            parse_mode="HTML", reply_markup=kb
        )
        return

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

        # Fail closed: a membership check error must never unlock the dashboard.
        subscribed = False

    if not subscribed:

        try:

            bot_username = (
                await bot.me()
            ).username

        except Exception:

            bot_username = None

        lang = current_lang or "id"
        missing = await get_missing_channels(bot, user_id)
        names = "\n".join(f"• <b>{x['name']}</b>" for x in missing)
        text = ("❌ <b>WAJIB JOIN CHANNEL</b>\n\nSilakan join channel yang belum kamu ikuti:\n" + names + "\n\nSetelah itu tekan <b>✅ Saya Sudah Join</b>.") if lang == "id" else ("❌ <b>CHANNEL JOIN REQUIRED</b>\n\nPlease join the channel(s) you have not joined:\n" + names + "\n\nThen press <b>✅ I Joined</b>.")
        await loading.edit_text(
            text,
            reply_markup=join_kb(bot_username, user_id, lang),
            parse_mode="HTML"
        )

        return

    # User sudah disimpan di awal process_start.

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

                            # Tambahkan referral + bonus secara atomic.
                            # referral_count adalah counter utama yang dipakai
                            # Account, Reward, dan Creator.
                            await pool.execute(
                                """
                                UPDATE users
                                SET
                                    referral_count = COALESCE(referral_count, 0) + 1,
                                    total_referral = COALESCE(total_referral, 0) + 1,
                                    balance = COALESCE(balance, 0) + 200,
                                    updated_at = NOW()
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

                            try:
                                from utils.referral import check_referral_reward
                                reward = await check_referral_reward(pool, ref_id)
                                if reward:
                                    await bot.send_message(
                                        ref_id,
                                        f"🎁 <b>Referral Reward</b>\n\n{reward}\n\nTerima kasih sudah mengajak member baru!",
                                        parse_mode="HTML"
                                    )
                            except Exception:
                                logging.exception("REFERRAL REWARD ERROR")

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
            creator_status,
            language
        FROM users
        WHERE user_id = $1
        """,
        user_id
    )

    lang = (user["language"] or "id") if user else "id"

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

    if lang == "en":
        text = (
            "<b>✨ MARKET DASHBOARD ✨</b>\n\n"
            f"ID: <code>{user_id}</code>\n"
            f"🎨 Creator: <b>{'VERIFIED ✅' if is_creator else 'NOT VERIFIED 🔒'}</b>\n"
            f"Balance: {balance_text}\n"
            f"Referrals: <b>{referral}</b>\n"
            "━━━━━━━━━━━━━━\n"
            "🔗 Referral Link:\n"
            f"<code>{ref_link}</code>\n\n"
            "Use the menu below to upload, buy, sell and manage your Telegram code."
        )
    else:
        text = (
            "<b>✨ MARKET DASHBOARD ✨</b>\n\n"
            f"ID : <code>{user_id}</code>\n"
            f"{creator_text}\n"
            f"Saldo : {balance_text}\n"
            f"Referral : <b>{referral}</b>\n"
            "━━━━━━━━━━━━━━\n"
            "🔗 Link Referral :\n"
            f"<code>{ref_link}</code>\n\n"
            "Gunakan menu di bawah untuk upload, jual, beli, dan mengelola code Telegram."
        )

    # =====================================================
    # EDIT LOADING
    # =====================================================

    try:

        await message.edit_text(
            text,
            parse_mode="HTML",
            reply_markup=home_kb(user_id, lang),
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
                reply_markup=home_kb(user_id, lang),
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


# =========================================================
# LANGUAGE SELECTION
# =========================================================
@router.callback_query(F.data.startswith("lang:"))
async def choose_language(call: CallbackQuery):
    lang = call.data.split(":", 1)[1]
    if lang not in ("id", "en"):
        return await call.answer("Invalid language.", show_alert=True)
    pool = await get_pool()
    await pool.execute("UPDATE users SET language=$1 WHERE user_id=$2", lang, call.from_user.id)
    try:
        await call.answer("Bahasa disimpan." if lang == "id" else "Language saved.")
    except Exception:
        pass

    missing = await get_missing_channels(call.bot, call.from_user.id)
    if missing:
        lines = (
            ["❌ <b>Kamu harus bergabung ke semua channel.</b>",
             "Masuk ke channel yang belum kamu ikuti, lalu tekan <b>✅ Saya Sudah Join</b>."]
            if lang == "id" else
            ["❌ <b>You must join all required channels.</b>",
             "Join every channel you left, then press <b>✅ I Joined</b>."]
        )
        for ch in missing:
            lines.append(f"• <b>{ch['name']}</b>")
        me = await call.bot.get_me()
        await call.message.edit_text(
            "\n\n".join(lines),
            parse_mode="HTML",
            reply_markup=join_kb(me.username, call.from_user.id, lang)
        )
        return

    user = await pool.fetchrow("SELECT username, fullname FROM users WHERE user_id=$1", call.from_user.id)
    display = (user["username"] or user["fullname"] or "unknown") if user else "unknown"
    await render_home_fast(call.bot, call.message, call.from_user.id, display)
