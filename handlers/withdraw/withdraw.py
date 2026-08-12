import logging

from aiogram import Router, F
from aiogram.types import CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.exceptions import TelegramBadRequest

from database import get_pool

from handlers.withdraw.utils import (
    withdraw_is_open,
    rupiah,
    MIN_WITHDRAW,
    WITHDRAW_FEE,
    WITHDRAW_NOMINALS,
    INSTANT_AMOUNT,
    INSTANT_FEE,
    INSTANT_MIN_BALANCE,
)


router = Router()

logger = logging.getLogger(__name__)


# =========================
# MENU WITHDRAW
# =========================

@router.callback_query(F.data == "withdraw")
async def withdraw_menu(call: CallbackQuery):

    await call.answer()


    kb = InlineKeyboardBuilder()


    kb.button(
        text="🏦 Rekening / E-Wallet",
        callback_data="ewallet"
    )


    # =========================
    # REGULER CHECK
    # =========================

    if withdraw_is_open():

        status = "🟢 <b>REGULER BUKA</b>"


        kb.button(
            text="💸 Withdraw Reguler",
            callback_data="withdraw_create"
        )


    else:

        status = "🔴 <b>REGULER TUTUP</b>"



    # =========================
    # INSTANT ALWAYS OPEN
    # =========================

    kb.button(
        text="⚡ Withdraw Instant",
        callback_data="withdraw_instant"
    )



    kb.button(
        text="📜 Riwayat Withdraw",
        callback_data="withdraw_history"
    )


    kb.button(
        text="🔙 Kembali",
        callback_data="home"
    )


    kb.adjust(1)



    text = (

        "💸 <b>WITHDRAW SALDO</b>\n"
        "━━━━━━━━━━━━━━\n\n"

        f"📌 Status : {status}\n\n"


        "🕘 <b>Jam Operasional Reguler</b>\n"
        "• Senin - Jumat\n"
        "• 09:00 - 19:00 WIB\n"
        "• Sabtu & Minggu Libur\n\n"


        "💸 <b>Withdraw Reguler</b>\n"
        f"• Minimal : {rupiah(MIN_WITHDRAW)}\n"
        f"• Fee Admin : {rupiah(WITHDRAW_FEE)}\n\n"


        "⚡ <b>Withdraw Instant</b>\n"
        f"• Nominal : {rupiah(INSTANT_AMOUNT)}\n"
        f"• Fee : {rupiah(INSTANT_FEE)}\n"
        f"• Minimal saldo : {rupiah(INSTANT_MIN_BALANCE)}\n\n"

        "⚡ Withdraw Instant tersedia 24 jam."
    )


    try:

        await call.message.edit_text(

            text,

            parse_mode="HTML",

            reply_markup=kb.as_markup()

        )


    except TelegramBadRequest as e:

        if "message is not modified" not in str(e).lower():

            logger.exception(e)



# =========================
# CREATE REGULER
# =========================

@router.callback_query(F.data == "withdraw_create")
async def withdraw_create(call: CallbackQuery):

    await call.answer()


    if not withdraw_is_open():

        return await call.answer(
            "Withdraw sedang tutup.",
            show_alert=True
        )


    pool = await get_pool()


    # ambil ewallet/bank user
    account = await pool.fetchrow(
        """
        SELECT
            id,
            method_name,
            account_number,
            account_name
        FROM user_payment_methods
        WHERE user_id=$1
        ORDER BY id
        LIMIT 1
        """,
        call.from_user.id
    )


    if not account:

        kb = InlineKeyboardBuilder()

        kb.button(
            text="➕ Tambah Rekening / E-Wallet",
            callback_data="ewallet"
        )

        kb.button(
            text="🔙 Kembali",
            callback_data="withdraw"
        )

        kb.adjust(1)


        return await call.message.edit_text(
            (
                "❌ <b>Rekening belum ada</b>\n\n"
                "Silakan simpan rekening atau e-wallet terlebih dahulu."
            ),
            parse_mode="HTML",
            reply_markup=kb.as_markup()
        )



    # cek saldo
    balance = await pool.fetchval(
        """
        SELECT balance
        FROM users
        WHERE user_id=$1
        """,
        call.from_user.id
    ) or 0



    kb = InlineKeyboardBuilder()


    for amount in WITHDRAW_NOMINALS:

        kb.button(
            text=rupiah(amount),
            callback_data=f"wd_amount:{amount}"
        )


    kb.button(
        text="❌ Batal",
        callback_data="withdraw"
    )


    kb.adjust(2)



    await call.message.edit_text(

        (
            "💸 <b>WITHDRAW REGULER</b>\n"
            "━━━━━━━━━━━━━━\n\n"

            f"💰 Saldo : <b>{rupiah(balance)}</b>\n\n"

            "🏦 <b>Tujuan:</b>\n"
            f"• {account['method_name']}\n"
            f"• {account['account_name']}\n"
            f"• <code>{account['account_number']}</code>\n\n"

            f"💸 Fee : {rupiah(WITHDRAW_FEE)}\n\n"

            "👇 Pilih nominal withdraw"
        ),

        parse_mode="HTML",
        reply_markup=kb.as_markup()
    )

# =========================
# CREATE INSTANT
# =========================

@router.callback_query(F.data == "withdraw_instant")
async def withdraw_instant(call: CallbackQuery):

    await call.answer()


    pool = await get_pool()


    # ambil rekening user
    account = await pool.fetchrow(
        """
        SELECT
            method_name,
            account_number,
            account_name

        FROM user_payment_methods

        WHERE user_id=$1

        ORDER BY id

        LIMIT 1
        """,
        call.from_user.id
    )


    if not account:

        kb = InlineKeyboardBuilder()

        kb.button(
            text="➕ Tambah Rekening / E-Wallet",
            callback_data="ewallet"
        )

        kb.button(
            text="🔙 Kembali",
            callback_data="withdraw"
        )

        kb.adjust(1)


        return await call.message.edit_text(

            (
                "❌ <b>Rekening belum ada</b>\n\n"
                "Tambahkan rekening atau e-wallet terlebih dahulu."
            ),

            parse_mode="HTML",
            reply_markup=kb.as_markup()
        )



    # ambil saldo
    balance = await pool.fetchval(
        """
        SELECT balance
        FROM users
        WHERE user_id=$1
        """,
        call.from_user.id
    ) or 0



    total = (
        INSTANT_AMOUNT
        +
        INSTANT_FEE
    )


    kb = InlineKeyboardBuilder()


    if balance >= total:

        kb.button(
            text="⚡ Request Withdraw Instant",
            callback_data="withdraw_instant_confirm"
        )

    else:

        kb.button(
            text="❌ Saldo Tidak Cukup",
            callback_data="withdraw"
        )


    kb.button(
        text="🔙 Kembali",
        callback_data="withdraw"
    )


    kb.adjust(1)



    await call.message.edit_text(

        (
            "⚡ <b>WITHDRAW INSTANT</b>\n"
            "━━━━━━━━━━━━━━\n\n"

            f"💰 Saldo : <b>{rupiah(balance)}</b>\n\n"

            "🏦 <b>Tujuan</b>\n"
            f"• {account['method_name']}\n"
            f"• {account['account_name']}\n"
            f"• <code>{account['account_number']}</code>\n\n"

            f"⚡ Nominal : <b>{rupiah(INSTANT_AMOUNT)}</b>\n"
            f"💸 Fee Instant : <b>{rupiah(INSTANT_FEE)}</b>\n"
            f"📉 Total Potong : <b>{rupiah(total)}</b>\n\n"

            "⚡ Withdraw instant diproses prioritas admin."
        ),

        parse_mode="HTML",
        reply_markup=kb.as_markup()
    )

# =========================
# PILIH NOMINAL
# =========================

@router.callback_query(F.data.startswith("wd_amount:"))
async def withdraw_amount(call: CallbackQuery):

    await call.answer()


    amount = int(
        call.data.split(":")[1]
    )


    if amount not in WITHDRAW_NOMINALS:

        return await call.answer(
            "Nominal tidak valid",
            show_alert=True
        )


    kb = InlineKeyboardBuilder()


    kb.button(
        text="✅ Lanjutkan",
        callback_data=f"withdraw_confirm:{amount}"
    )

    kb.button(
        text="❌ Batal",
        callback_data="withdraw"
    )

    kb.adjust(1)


    await call.message.edit_text(

        (
            "💸 <b>DETAIL WITHDRAW</b>\n"
            "━━━━━━━━━━━━━━\n\n"

            f"💰 Nominal : <b>{rupiah(amount)}</b>\n"
            f"💸 Fee : <b>{rupiah(WITHDRAW_FEE)}</b>\n"
            f"📉 Total Potong : <b>{rupiah(amount + WITHDRAW_FEE)}</b>\n\n"

            "Klik lanjutkan untuk membuat withdraw."
        ),

        parse_mode="HTML",
        reply_markup=kb.as_markup()
    )

