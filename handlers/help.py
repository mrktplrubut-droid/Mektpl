import asyncio

from aiogram import Router, F
from aiogram.types import CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder


router = Router()


HELP_CACHE = {}


def get_cache(key):
    return HELP_CACHE.get(key)


def set_cache(key, value):
    HELP_CACHE[key] = value


async def loading(call: CallbackQuery):

    try:
        await call.message.edit_text("⏳ Loading...")
    except:
        pass

    await asyncio.sleep(0.3)


def kb_builder(buttons):

    builder = InlineKeyboardBuilder()

    for text, data in buttons:
        builder.button(
            text=text,
            callback_data=data
        )

    builder.adjust(1)

    return builder.as_markup()



# =====================================
# HELP MENU
# =====================================

@router.callback_query(F.data == "help")
async def help_menu(call: CallbackQuery):

    await loading(call)

    text = (
        "━━━━━━━━━━━━━━\n"
        "❓ <b>HELP CENTER</b>\n"
        "━━━━━━━━━━━━━━\n\n"
        "Selamat datang di pusat bantuan.\n\n"
        "Silakan pilih panduan yang ingin dipelajari.\n\n"
        "Tutorial dibuat agar pengguna baru dapat memahami sistem BOT MARKET dengan mudah."
    )


    kb = kb_builder([
        ("📤 Cara Upload File", "help_upfile"),
        ("📥 Cara Get File", "help_getfile"),
        ("💰 Cara Mendapatkan Cuan", "help_money"),
        ("🏦 Cara Withdraw", "help_withdraw"),
        ("🏠 Home", "home"),
    ])


    await call.message.edit_text(
        text,
        reply_markup=kb,
        parse_mode="HTML"
    )

    await call.answer()



# =====================================
# TEMPLATE
# =====================================

async def help_template(call, key, content):

    cache = get_cache(key)

    if cache is None:
        set_cache(key, content)
        cache = content


    await loading(call)


    kb = kb_builder([
        ("🔙 Kembali", "help")
    ])


    await call.message.edit_text(
        cache,
        reply_markup=kb,
        parse_mode="HTML"
    )


    await call.answer()



# =====================================
# UPLOAD FILE
# =====================================

@router.callback_query(F.data == "help_upfile")
async def help_upfile(call: CallbackQuery):

    await help_template(
        call,
        "upfile",
        """
━━━━━━━━━━━━━━
📤 <b>CARA UPLOAD FILE</b>
━━━━━━━━━━━━━━

1️⃣ Masuk ke menu <b>Upload File</b>

2️⃣ Kirim file yang ingin dijual.

Support:
• Foto
• Video
• Dokumen
• ZIP
• RAR
• APK
• PDF
• Dan file lainnya

3️⃣ Setelah selesai upload,
tekan tombol selesai.

4️⃣ Masukkan harga file.

Contoh:

1000
5000
10000
25000

5️⃣ Bot akan membuat CODE otomatis.

6️⃣ Bagikan CODE tersebut kepada pembeli.

Jika ada pembelian,
saldo akan masuk otomatis.

━━━━━━━━━━━━━━

Tips:

✔ Upload file berkualitas.
✔ Gunakan judul menarik.
✔ Promosikan CODE kamu.
"""
    )



# =====================================
# GET FILE
# =====================================

@router.callback_query(F.data == "help_getfile")
async def help_getfile(call: CallbackQuery):

    await help_template(
        call,
        "getfile",
        """
━━━━━━━━━━━━━━
📥 <b>CARA GET FILE</b>
━━━━━━━━━━━━━━

1️⃣ Masuk menu Get File.

2️⃣ Masukkan CODE file.

Contoh:

ABC123XYZ

3️⃣ Sistem akan mengecek CODE.

Jika gratis:
✅ File langsung dikirim.

Jika berbayar:
💳 Lakukan pembayaran terlebih dahulu.

4️⃣ Setelah pembayaran berhasil,
file akan dikirim otomatis.

━━━━━━━━━━━━━━

Semua proses dilakukan otomatis oleh sistem.
"""
    )



# =====================================
# MENDAPATKAN CUAN
# =====================================

@router.callback_query(F.data == "help_money")
async def help_money(call: CallbackQuery):

    await help_template(
        call,
        "money",
        """
━━━━━━━━━━━━━━
💰 <b>CARA MENDAPATKAN CUAN</b>
━━━━━━━━━━━━━━

Kamu bisa mendapatkan penghasilan dari file yang dijual.

Caranya:

① Upload file.

② Tentukan harga.

③ Bot membuat CODE.

④ Bagikan CODE ke:

• Telegram
• WhatsApp
• Facebook
• Instagram
• TikTok
• Website

⑤ Setiap pembelian akan masuk ke saldo akun.

━━━━━━━━━━━━━━

Semakin banyak file dan promosi,
semakin besar peluang penghasilan.
"""
    )



# =====================================
# WITHDRAW
# =====================================

@router.callback_query(F.data == "help_withdraw")
async def help_withdraw(call: CallbackQuery):

    await help_template(
        call,
        "withdraw",
        """
━━━━━━━━━━━━━━
🏦 <b>CARA WITHDRAW</b>
━━━━━━━━━━━━━━

1️⃣ Pastikan saldo mencukupi.

2️⃣ Masuk menu Withdraw.

3️⃣ Pilih metode pembayaran.

Contoh:

• DANA
• OVO
• GoPay
• ShopeePay
• Bank

4️⃣ Masukkan nominal.

5️⃣ Kirim permintaan.

Admin akan memproses sesuai antrean.

━━━━━━━━━━━━━━

Pastikan data pencairan benar.
"""
    )
