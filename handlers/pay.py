import json
import logging
import qrcode

from io import BytesIO

from aiogram import Router, F
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    BufferedInputFile,
)
import secrets
from database import fetchrow, execute
from utils.redis_client import (
    safe_set,
    safe_get,
    safe_delete
)

from utils.bayargg import BayarGG

from config import (
    STORAGE_CHANNEL_ID,
    NOTIF_CHANNEL_ID,
    ADMIN_IDS,
    MANUAL_QR_FILE_ID
)


logger = logging.getLogger(__name__)

router = Router()


# ==================================================
# CONFIG
# ==================================================

PAY_LOCK_TTL = 30
MEDIA_TTL = 3600

PER_PAGE = 10

CHECK_LOCK = set()



# ==================================================
# HELPER
# ==================================================

def mask_user_id(user_id: int):

    uid = str(user_id)

    if len(uid) <= 4:
        return "****"

    return (
        uid[:2]
        + "****"
        + uid[-2:]
    )



async def send_upgrade_notif(
    bot,
    user_id,
    tier
):

    try:

        masked = mask_user_id(user_id)


        if tier.lower() == "vip":

            text = (
                "🌟 <b>VIP UPGRADE</b>\n\n"
                f"👤 User: <code>{masked}</code>\n"
                "📦 Paket: VIP"
            )


        elif tier.lower() == "vvip":

            text = (
                "👑 <b>VVIP UPGRADE</b>\n\n"
                f"👤 User: <code>{masked}</code>\n"
                "📦 Paket: VVIP"
            )


        else:
            return



        await bot.send_message(
            NOTIF_CHANNEL_ID,
            text,
            parse_mode="HTML"
        )


    except Exception:

        logger.exception(
            "UPGRADE NOTIF ERROR"
        )



# ==================================================
# KEYBOARD
# ==================================================

def payment_method_keyboard(code):

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="⚡ Bayar Otomatis",
                    callback_data=f"auto:{code}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="📷 Bayar Manual",
                    callback_data=f"manual:{code}"
                )
            ]
        ]
    )



def manual_payment_keyboard(code):

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Saya Sudah Bayar",
                    callback_data=f"manualcheck:{code}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="❌ Batal",
                    callback_data="close"
                )
            ]
        ]
    )



def payment_check_keyboard(invoice):

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔄 Cek Pembayaran",
                    callback_data=f"check:{invoice}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="❌ Batalkan",
                    callback_data=f"cancel:{invoice}"
                )
            ]
        ]
    )



def media_keyboard(
    media_id,
    page,
    total
):

    max_page = (
        total + PER_PAGE - 1
    ) // PER_PAGE


    buttons = []

    nav = []


    if page > 1:
        nav.append(
            InlineKeyboardButton(
                text="⬅️",
                callback_data=f"mp:{media_id}:{page-1}"
            )
        )


    nav.append(
        InlineKeyboardButton(
            text=f"{page}/{max_page}",
            callback_data="none"
        )
    )


    if page < max_page:
        nav.append(
            InlineKeyboardButton(
                text="➡️",
                callback_data=f"mp:{media_id}:{page+1}"
            )
        )


    buttons.append(nav)


    buttons.append(
        [
            InlineKeyboardButton(
                text="📤 Kirim Halaman",
                callback_data=f"sp:{media_id}:{page}"
            )
        ]
    )


    buttons.append(
        [
            InlineKeyboardButton(
                text="📦 Kirim Semua",
                callback_data=f"sa:{media_id}"
            )
        ]
    )


    return InlineKeyboardMarkup(
        inline_keyboard=buttons
    )

# ==================================================
# FINISH PAYMENT CORE
# ==================================================

async def finish_payment(
    bot,
    purchase,
    file,
    invoice,
    message
):

    """
    Semua pembayaran masuk sini:
    - QRIS
    - Manual Admin
    """


    if purchase["status"] == "paid":
        return False



    # =============================
    # MEDIA PARSE
    # =============================

    media_data = file["media"]


    if isinstance(media_data, str):

        try:
            media_list = json.loads(media_data)

        except Exception:

            media_list = []

    else:

        media_list = media_data or []



    media_list = [
        x
        for x in media_list
        if isinstance(x, dict)
        and x.get("message_id")
    ]



    if not media_list:

        await message.answer(
            "❌ Media kosong"
        )

        return False



    # =============================
    # CREATE MEDIA SESSION
    # =============================

    media_id = secrets.token_hex(8)


    await safe_set(
        f"paidmedia:{media_id}",
        {
            "media": media_list,
            "share_media": file["share_media"],
            "invoice": invoice
        },
        ex=MEDIA_TTL
    )



    # =============================
    # UPDATE PAYMENT
    # =============================

    updated = await execute(
        """
        UPDATE file_purchases
        SET status='paid'
        WHERE id=$1
        AND status='pending'
        """,
        purchase["id"]
    )


    if not updated:

        await safe_delete(
            f"paidmedia:{media_id}"
        )

        return False



    # =============================
    # UPDATE BUY COUNT
    # =============================

    await execute(
        """
        UPDATE files
        SET buy_count =
        COALESCE(buy_count,0)+1
        WHERE code=$1
        """,
        file["code"]
    )



    # =============================
    # SELLER PROFIT
    # =============================

    price = file["price"] or 0

    income = int(
        price * 0.5
    )


    await execute(
        """
        UPDATE users
        SET
        balance =
        COALESCE(balance,0)+$1,

        total_earn =
        COALESCE(total_earn,0)+$1

        WHERE chat_id=$2
        """,
        income,
        file["owner_id"]
    )



    await execute(
        """
        INSERT INTO transactions
        (
            user_id,
            type,
            amount,
            description
        )
        VALUES
        ($1,$2,$3,$4)
        """,
        file["owner_id"],
        "file_sale",
        income,
        f"Pendapatan file {file['code']}"
    )



    # =============================
    # VIP / VVIP
    # =============================

    code_lower = file["code"].lower()


    if "vvip" in code_lower:

        await send_upgrade_notif(
            bot,
            purchase["user_id"],
            "vvip"
        )


    elif "vip" in code_lower:

        await send_upgrade_notif(
            bot,
            purchase["user_id"],
            "vip"
        )



    # =============================
    # NOTIF CHANNEL
    # =============================

    try:

        masked = mask_user_id(
            purchase["user_id"]
        )


        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="🛒 Buy Now",
                        url=f"https://t.me/mktplbot?start={file['code']}"
                    )
                ]
            ]
        )


        await bot.send_message(
            NOTIF_CHANNEL_ID,
            (
                "💸 <b>FILE PAYMENT SUCCESS</b>\n\n"
                f"📄 Judul: <b>{file['title']}</b>\n"
                f"📁 Code: <code>{file['code']}</code>\n"
                f"👤 User: <code>{masked}</code>"
            ),
            parse_mode="HTML",
            reply_markup=keyboard
        )


    except Exception:

        logger.exception(
            "NOTIF ERROR"
        )



    # =============================
    # DELETE QR MESSAGE
    # =============================

    try:

        if (
            purchase.get("qr_message_id")
            and purchase.get("qr_chat_id")
        ):

            await bot.delete_message(
                purchase["qr_chat_id"],
                purchase["qr_message_id"]
            )


    except Exception:

        pass



    # =============================
    # SEND MEDIA MENU
    # =============================

    total = len(media_list)


    await message.answer(
        (
            "🎉 <b>Pembayaran berhasil</b>\n\n"
            f"📦 Total File: <b>{total}</b>\n\n"
            "Silahkan pilih pengiriman:"
        ),
        parse_mode="HTML",
        reply_markup=media_keyboard(
            media_id,
            1,
            total
        )
    )


    return True

@router.callback_query(F.data.startswith("pay:"))
async def choose_payment(call: CallbackQuery):

    code = call.data.split(":")[1]

    file = await fetchrow(
        """
        SELECT *
        FROM files
        WHERE code=$1
        """,
        code
    )

    if not file:
        return await call.answer(
            "File tidak ditemukan",
            show_alert=True
        )


    await call.message.edit_text(
        (
            "💳 <b>PILIH PEMBAYARAN</b>\n\n"
            f"📦 File: <b>{file['title']}</b>\n"
            f"💰 Harga: Rp {file['price']:,}\n\n"
            "Silahkan pilih metode pembayaran."
        ).replace(",", "."),
        parse_mode="HTML",
        reply_markup=payment_method_keyboard(code)
    )

    await call.answer()
    

# ==================================================
# AUTO PAYMENT QRIS
# ==================================================

@router.callback_query(F.data.startswith("auto:"))
async def pay_file(call: CallbackQuery):

    user_id = call.from_user.id
    code = call.data.split(":")[1]


    await call.answer(
        "⏳ Membuat pembayaran..."
    )


    file = await fetchrow(
        """
        SELECT *
        FROM files
        WHERE code=$1
        """,
        code
    )


    if not file:

        return await call.answer(
            "File tidak ditemukan",
            show_alert=True
        )


    price = file["price"] or 0


    data = await BayarGG.create_payment(
        amount=price,
        description=f"File {code}",
        customer_name=call.from_user.full_name
    )


    if not data:

        return await call.answer(
            "Gagal membuat QRIS",
            show_alert=True
        )


    invoice = data["invoice_id"]

    qr_string = data["qris_string"]


    await execute(
        """
        INSERT INTO file_purchases
        (
        user_id,
        file_code,
        owner_id,
        paid_price,
        payment_id,
        status,
        created_at
        )
        VALUES
        ($1,$2,$3,$4,$5,'pending',NOW())
        """,
        user_id,
        code,
        file["owner_id"],
        price,
        invoice
    )


    qr = qrcode.make(
        qr_string
    )


    buffer = BytesIO()

    qr.save(
        buffer,
        "PNG"
    )

    buffer.seek(0)


    msg = await call.message.answer_photo(
        BufferedInputFile(
            buffer.getvalue(),
            filename="qris.png"
        ),
        caption=(
            "💳 <b>PAYMENT QRIS</b>\n\n"
            f"Invoice:\n<code>{invoice}</code>\n\n"
            f"Total:\nRp {price:,}\n\n"
            "Scan QR untuk pembayaran."
        ).replace(",", "."),
        parse_mode="HTML",
        reply_markup=payment_check_keyboard(invoice)
    )


    await execute(
        """
        UPDATE file_purchases
        SET
        qr_message_id=$1,
        qr_chat_id=$2
        WHERE payment_id=$3
        """,
        msg.message_id,
        msg.chat.id,
        invoice
    )


# ==================================================
# CHECK PAYMENT QRIS
# ==================================================

@router.callback_query(F.data.startswith("check:"))
async def check_payment(call: CallbackQuery):

    invoice = call.data.split(":")[1]


    if invoice in CHECK_LOCK:

        return await call.answer(
            "⏳ Sedang diproses...",
            show_alert=True
        )


    CHECK_LOCK.add(invoice)


    try:

        await call.answer(
            "🔄 Mengecek pembayaran..."
        )


        result = await BayarGG.check_payment(
            invoice
        )


        if not result:

            return await call.answer(
                "❌ Gagal cek pembayaran",
                show_alert=True
            )


        status = (
            result.get("status")
            or result.get("payment_status")
        )


        if status != "paid":

            return await call.answer(
                "⏳ Belum dibayar",
                show_alert=True
            )


        purchase = await fetchrow(
            """
            SELECT *
            FROM file_purchases
            WHERE payment_id=$1
            """,
            invoice
        )


        if not purchase:

            return await call.answer(
                "Data pembayaran tidak ditemukan",
                show_alert=True
            )


        file = await fetchrow(
            """
            SELECT *
            FROM files
            WHERE code=$1
            """,
            purchase["file_code"]
        )


        if not file:

            return await call.answer(
                "File tidak ditemukan",
                show_alert=True
            )


        await finish_payment(
            call.bot,
            purchase,
            file,
            invoice,
            call.message
        )


    except Exception:

        logger.exception(
            "CHECK PAYMENT ERROR"
        )


        await call.message.answer(
            "❌ Terjadi error saat cek pembayaran"
        )


    finally:

        CHECK_LOCK.discard(invoice)


@router.callback_query(F.data=="close")
async def close_payment(call: CallbackQuery):

    await call.message.delete()

    await call.answer(
        "Pembayaran dibatalkan"
    )



# ==================================================
# MANUAL PAYMENT QR
# ==================================================

@router.callback_query(F.data.startswith("manual:"))
async def manual_payment(call: CallbackQuery):

    code = call.data.split(":")[1]


    file = await fetchrow(
        """
        SELECT *
        FROM files
        WHERE code=$1
        """,
        code
    )


    if not file:

        return await call.answer(
            "File tidak ditemukan",
            show_alert=True
        )


    # =============================
    # CEK PEMBELIAN PENDING
    # =============================

    existing = await fetchrow(
        """
        SELECT *
        FROM file_purchases
        WHERE user_id=$1
        AND file_code=$2
        AND status='pending'
        ORDER BY id DESC
        LIMIT 1
        """,
        call.from_user.id,
        code
    )


    # =============================
    # BUAT DATA PEMBELIAN
    # =============================

    if not existing:

        await execute(
            """
            INSERT INTO file_purchases
            (
                user_id,
                file_code,
                owner_id,
                paid_price,
                payment_id,
                status,
                created_at
            )
            VALUES
            (
                $1,
                $2,
                $3,
                $4,
                $5,
                'pending',
                NOW()
            )
            """,
            call.from_user.id,
            code,
            file["owner_id"],
            file["price"],
            f"MANUAL-{call.from_user.id}-{code}"
        )


    caption = (
        "📷 <b>PEMBAYARAN MANUAL</b>\n\n"
        f"📄 File : <b>{file['title']}</b>\n"
        f"💰 Harga : <b>Rp {file['price']:,}</b>\n\n"
        "Silahkan scan QR di atas.\n\n"
        "⚠️ Bayar sesuai nominal.\n"
        "Setelah bayar tekan tombol dibawah."
    ).replace(",", ".")


    await call.message.answer_photo(
        MANUAL_QR_FILE_ID,
        caption=caption,
        parse_mode="HTML",
        reply_markup=manual_payment_keyboard(code)
    )


    await call.answer(
        "Silahkan lakukan pembayaran"
    )



# ==================================================
# REQUEST MANUAL CHECK
# ==================================================

@router.callback_query(F.data.startswith("manualcheck:"))
async def manual_check(call: CallbackQuery):

    code = call.data.split(":")[1]


    file = await fetchrow(
        """
        SELECT *
        FROM files
        WHERE code=$1
        """,
        code
    )


    if not file:

        return await call.answer(
            "File tidak ditemukan",
            show_alert=True
        )


    # =============================
    # CEK PEMBELIAN PENDING
    # =============================

    purchase = await fetchrow(
        """
        SELECT *
        FROM file_purchases
        WHERE user_id=$1
        AND file_code=$2
        AND status='pending'
        ORDER BY id DESC
        LIMIT 1
        """,
        call.from_user.id,
        code
    )


    if not purchase:

        return await call.answer(
            "Transaksi tidak ditemukan. Silahkan ulangi pembayaran.",
            show_alert=True
        )


    text = (
        "📥 <b>MANUAL PAYMENT CHECK</b>\n\n"
        f"👤 User: <code>{call.from_user.id}</code>\n"
        f"📄 File: <b>{file['title']}</b>\n"
        f"🔑 Code: <code>{code}</code>\n"
        f"💰 Harga: Rp {purchase['paid_price']:,}"
    ).replace(",", ".")


    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Approve",
                    callback_data=f"approve:{purchase['id']}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="❌ Reject",
                    callback_data=f"reject:{purchase['id']}"
                )
            ]
        ]
    )


    for admin in ADMIN_IDS:

        try:

            await call.bot.send_message(
                admin,
                text,
                parse_mode="HTML",
                reply_markup=keyboard
            )

        except Exception:

            logger.exception(
                "SEND ADMIN ERROR"
            )


    await call.message.answer(
        "✅ Permintaan verifikasi pembayaran dikirim ke admin."
    )


    await call.answer()


# ==================================================
# APPROVE MANUAL PAYMENT
# ==================================================

@router.callback_query(F.data.startswith("approve:"))
async def approve_manual(call: CallbackQuery):

    _, purchase_id = call.data.split(":")

    purchase_id = int(purchase_id)


    # =============================
    # AMBIL PEMBELIAN
    # =============================

    purchase = await fetchrow(
        """
        SELECT *
        FROM file_purchases
        WHERE id=$1
        AND status='pending'
        """,
        purchase_id
    )


    if not purchase:

        return await call.answer(
            "❌ Pembelian tidak ditemukan / sudah diproses",
            show_alert=True
        )


    user_id = purchase["user_id"]
    code = purchase["file_code"]



    # =============================
    # AMBIL FILE
    # =============================

    file = await fetchrow(
        """
        SELECT *
        FROM files
        WHERE code=$1
        """,
        code
    )


    if not file:

        return await call.answer(
            "❌ File tidak ditemukan",
            show_alert=True
        )



    await call.answer(
        "⏳ Memproses pembayaran..."
    )



    # =============================
    # KIRIM PESAN KE USER
    # =============================

    try:

        user_message = await call.bot.send_message(
            user_id,
            "⏳ Pembayaran sedang diproses..."
        )


    except Exception:

        logger.exception(
            "USER MESSAGE ERROR"
        )

        return await call.answer(
            "❌ User belum pernah membuka bot",
            show_alert=True
        )



    # =============================
    # FINISH PAYMENT
    # =============================

    try:

        success = await finish_payment(
            call.bot,
            purchase,
            file,
            purchase["payment_id"],
            user_message
        )


        if not success:

            return await call.answer(
                "❌ Pembayaran gagal diproses",
                show_alert=True
            )


    except Exception:

        logger.exception(
            "APPROVE FINISH ERROR"
        )

        return await call.answer(
            "❌ Error proses pembayaran",
            show_alert=True
        )



    # =============================
    # UPDATE PESAN ADMIN
    # =============================

    try:

        await call.message.edit_text(
            (
                "✅ <b>PEMBAYARAN DISETUJUI</b>\n\n"
                f"👤 User: <code>{user_id}</code>\n"
                f"📦 File: <b>{file['title']}</b>\n"
                f"🔑 Code: <code>{code}</code>"
            ),
            parse_mode="HTML"
        )


    except Exception:

        pass

# ==================================================
# REJECT MANUAL PAYMENT
# ==================================================

@router.callback_query(F.data.startswith("reject:"))
async def reject_manual(call: CallbackQuery):

    _, user_id, code = call.data.split(":")


    user_id = int(user_id)


    try:

        await call.bot.send_message(
            user_id,
            (
                "❌ <b>Pembayaran Ditolak</b>\n\n"
                f"📦 File:\n<code>{code}</code>\n\n"
                "Silahkan lakukan pembayaran ulang."
            ),
            parse_mode="HTML"
        )


    except Exception:

        pass



    await call.message.edit_text(
        "❌ Pembayaran ditolak."
    )


    await call.answer()



# ==================================================
# CANCEL PAYMENT
# ==================================================

@router.callback_query(F.data.startswith("cancel:"))
async def cancel_payment(call: CallbackQuery):

    invoice = call.data.split(":")[1]


    payment = await fetchrow(
        """
        SELECT *
        FROM file_purchases
        WHERE payment_id=$1
        """,
        invoice
    )


    if not payment:

        return await call.answer(
            "❌ Data tidak ditemukan",
            show_alert=True
        )


    if payment["status"] == "paid":

        return await call.answer(
            "✅ Sudah dibayar",
            show_alert=True
        )


    try:

        await BayarGG.cancel_payment(
            invoice
        )


    except Exception:

        logger.exception(
            "CANCEL PAYMENT ERROR"
        )



    await execute(
        """
        UPDATE file_purchases
        SET status='cancel'
        WHERE payment_id=$1
        """,
        invoice
    )


    await safe_delete(
        f"paidmedia:{invoice}"
    )


    try:

        if (
            payment["qr_message_id"]
            and payment["qr_chat_id"]
        ):

            await call.bot.delete_message(
                payment["qr_chat_id"],
                payment["qr_message_id"]
            )


    except Exception:

        pass



    await call.answer(
        "❌ Pembayaran dibatalkan"
    )


    await call.message.answer(
        "❌ <b>Pembayaran dibatalkan.</b>",
        parse_mode="HTML"
    )


# ==================================================
# SEND PAGE MEDIA
# ==================================================

@router.callback_query(F.data.startswith("sp:"))
async def send_page_media(call: CallbackQuery):

    _, media_id, page = call.data.split(":")

    page = int(page)


    data = await safe_get(
        f"paidmedia:{media_id}"
    )


    if not data:

        return await call.answer(
            "❌ Data media sudah expired",
            show_alert=True
        )


    media_list = data.get("media", [])


    start = (page - 1) * PER_PAGE
    end = start + PER_PAGE


    items = media_list[start:end]


    if not items:

        return await call.answer(
            "❌ Halaman tidak ditemukan",
            show_alert=True
        )


    await call.answer(
        "📤 Mengirim file..."
    )


    sent = 0


    for item in items:

        try:

            await call.bot.copy_message(
                chat_id=call.from_user.id,
                from_chat_id=STORAGE_CHANNEL_ID,
                message_id=item["message_id"]
            )

            sent += 1


        except Exception:

            logger.exception(
                "SEND PAGE ERROR"
            )



    await call.message.answer(
        (
            f"✅ Halaman {page} selesai\n\n"
            f"📦 Terkirim: {sent}/{len(items)} file"
        )
    )



# ==================================================
# SEND ALL MEDIA
# ==================================================

@router.callback_query(F.data.startswith("sa:"))
async def send_all_media(call: CallbackQuery):

    _, media_id = call.data.split(":")


    data = await safe_get(
        f"paidmedia:{media_id}"
    )


    if not data:

        return await call.answer(
            "❌ Data media expired",
            show_alert=True
        )


    media_list = data.get("media", [])


    if not media_list:

        return await call.answer(
            "❌ Media kosong",
            show_alert=True
        )


    await call.answer(
        "📦 Mengirim semua file..."
    )


    progress = await call.message.answer(
        f"⏳ Mengirim 0/{len(media_list)}"
    )


    sent = 0


    for index, item in enumerate(
        media_list,
        start=1
    ):

        try:

            await call.bot.copy_message(
                chat_id=call.from_user.id,
                from_chat_id=STORAGE_CHANNEL_ID,
                message_id=item["message_id"]
            )


            sent += 1



            if index % 5 == 0:

                try:

                    await progress.edit_text(
                        f"⏳ Mengirim {index}/{len(media_list)}"
                    )

                except Exception:

                    pass



        except Exception:

            logger.exception(
                "SEND ALL ERROR"
            )



    try:

        await progress.edit_text(
            (
                "✅ Semua file selesai\n\n"
                f"📦 Berhasil: {sent}/{len(media_list)}"
            )
        )


    except Exception:

        pass

# ==================================================
# MEDIA PAGE NAVIGATION
# ==================================================

@router.callback_query(F.data.startswith("mp:"))
async def media_page(call: CallbackQuery):

    _, media_id, page = call.data.split(":")

    page = int(page)


    data = await safe_get(
        f"paidmedia:{media_id}"
    )


    if not data:

        return await call.answer(
            "❌ Session media sudah expired",
            show_alert=True
        )


    media_list = data.get(
        "media",
        []
    )


    if not media_list:

        return await call.answer(
            "❌ Media tidak ditemukan",
            show_alert=True
        )


    total = len(
        media_list
    )


    await call.message.edit_reply_markup(
        reply_markup=media_keyboard(
            media_id,
            page,
            total
        )
    )


    await call.answer()
