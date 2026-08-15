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
    except Exception:
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


# =========================================================
# HELP MENU
# =========================================================

@router.callback_query(F.data == "help")
async def help_menu(call: CallbackQuery):

    await loading(call)

    text = (
        "❓ <b>HELP CENTER</b>\n\n"
        "Selamat datang di <b>BOT MARKET</b>. 🤖\n\n"
        "Pelajari cara menggunakan fitur utama bot.\n\n"
        "📤 <b>Upload File</b> — Cara upload dan membuat CODE.\n"
        "📥 <b>Get File</b> — Cara mengambil file menggunakan CODE.\n"
        "💰 <b>Mendapatkan Cuan</b> — Cara mendapatkan penghasilan.\n"
        "🏦 <b>Withdraw</b> — Cara mencairkan saldo.\n\n"
        "👇 Pilih panduan:"
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


# =========================================================
# TEMPLATE
# =========================================================

async def help_template(
    call: CallbackQuery,
    key: str,
    content: str
):
    cache = get_cache(key)

    if cache is None:
        set_cache(key, content)
        cache = content

    await loading(call)

    kb = kb_builder([
        ("🔙 Kembali ke Help", "help"),
    ])

    await call.message.edit_text(
        cache,
        reply_markup=kb,
        parse_mode="HTML"
    )

    await call.answer()


# =========================================================
# UPLOAD FILE
# =========================================================

@router.callback_query(F.data == "help_upfile")
async def help_upfile(call: CallbackQuery):

    await help_template(
        call,
        "upfile",
        """
📤 <b>CARA UPLOAD FILE</b>

<b>1. Mulai Upload</b>
Tekan menu 📤 <b>Upload File</b>.

<b>2. Kirim File</b>
Kirim file yang ingin disimpan.

Support:
• 📄 Dokumen
• 🎬 Video
• 🖼 Foto
• ZIP
• RAR
• APK
• PDF
• Dan file Telegram lainnya.

📦 Maksimal <b>200 media</b> dalam satu CODE.

<b>3. Selesai Upload</b>
Jika semua file sudah dikirim, tekan:
⏹ <b>STOP & SAVE</b>

Jika ingin membatalkan:
❌ <b>BATAL</b>

<b>4. Pilih Mode</b>
🔗 <b>Share Media</b>
File dapat digunakan melalui sistem share/link jika tersedia.

🔒 <b>Private</b>
File hanya dapat diakses menggunakan CODE.

<b>5. Masukkan Judul</b>
Contoh:
<code>Premium Pack 2026</code>

Atau ketik <code>/skip</code> untuk menggunakan judul otomatis.

<b>6. Pilih Tipe File</b>
🆓 <b>FREE</b> — File gratis.
💰 <b>PAID</b> — File berbayar.

⚠️ PAID hanya tersedia untuk:
🎨 <b>Kreator Terverifikasi</b> ✅

<b>Harga PAID</b>
Minimal <b>Rp1.000</b>.

Contoh:
<code>1000</code>
<code>5000</code>
<code>10000</code>

<b>7. CODE Dibuat</b>
Setelah berhasil disimpan, bot membuat CODE otomatis.

Contoh:
<code>8ae2o91i...</code>

Bagikan CODE tersebut kepada pengguna atau calon pembeli.

💡 <b>Tips</b>
✔ Gunakan judul yang jelas.
✔ Upload file berkualitas.
✔ Pastikan file sudah benar.
✔ Simpan CODE dengan baik.
✔ Promosikan CODE untuk mendapatkan pembeli.
"""
    )


# =========================================================
# GET FILE
# =========================================================

@router.callback_query(F.data == "help_getfile")
async def help_getfile(call: CallbackQuery):

    await help_template(
        call,
        "getfile",
        """
📥 <b>CARA GET FILE</b>

<b>1. Buka Get File</b>
Tekan menu 📥 <b>Get File</b>.

<b>2. Masukkan CODE</b>
Kirim CODE file.

Contoh:
<code>8ae2o91i...</code>

Pastikan CODE yang dikirim benar.

<b>Jika FREE</b>
🆓 File gratis dan tidak memerlukan pembayaran.

Bot akan langsung memproses dan mengirim file.

<b>Jika PAID</b>
💰 Bot akan menampilkan harga file.

💳 Lakukan pembayaran sesuai nominal yang ditampilkan.

Setelah pembayaran berhasil:
✅ Pembayaran diverifikasi.
📦 File diproses.
📤 File dikirim kepada pembeli.

⚠️ <b>Penting</b>
Jangan mengubah nominal pembayaran.

Pembayaran harus terdeteksi oleh sistem sebelum file dapat diberikan.

💡 <b>Tips</b>
✔ Pastikan CODE benar.
✔ Bayar sesuai nominal.
✔ Jangan mengirim bukti pembayaran palsu.
✔ Jika pembayaran berhasil tetapi file belum diterima, hubungi admin.
"""
    )


# =========================================================
# MENDAPATKAN CUAN
# =========================================================

@router.callback_query(F.data == "help_money")
async def help_money(call: CallbackQuery):

    await help_template(
        call,
        "money",
        """
💰 <b>CARA MENDAPATKAN CUAN</b>

BOT MARKET memungkinkan Kreator mendapatkan penghasilan dari file yang dijual.

<b>Siapa yang bisa menjual?</b>
🎨 <b>Kreator Terverifikasi</b> ✅

Kreator dapat membuat:
🆓 File FREE
💰 File PAID

<b>Cara mulai</b>
① Ikuti proses menjadi Kreator.
② Tunggu sampai disetujui.
③ Pastikan status menjadi 🎨 <b>Kreator Terverifikasi</b>.
④ Masuk 📤 <b>Upload File</b>.
⑤ Upload file.
⑥ Pilih 💰 <b>PAID</b>.
⑦ Tentukan harga.

💰 Harga minimal: <b>Rp1.000</b>.

<b>Setelah file dibuat</b>
Bot akan membuat CODE otomatis.

CODE dapat dipromosikan melalui:
• Telegram
• WhatsApp
• Facebook
• Instagram
• TikTok
• Website
• Komunitas
• Media lainnya

<b>Jika ada pembelian</b>
💳 Pembeli melakukan pembayaran
⬇️
🤖 Sistem memproses pembayaran
⬇️
📦 File diberikan kepada pembeli
⬇️
💰 Penghasilan tercatat ke akun Kreator

💡 <b>Tips meningkatkan penjualan</b>
✔ Gunakan judul menarik.
✔ Berikan informasi yang jelas.
✔ Upload file berkualitas.
✔ Tentukan harga yang sesuai.
✔ Promosikan CODE secara rutin.

Semakin banyak pembelian, semakin besar potensi penghasilan.
"""
    )


# =========================================================
# WITHDRAW
# =========================================================

@router.callback_query(F.data == "help_withdraw")
async def help_withdraw(call: CallbackQuery):

    await help_template(
        call,
        "withdraw",
        """
🏦 <b>CARA WITHDRAW</b>

Withdraw digunakan untuk mencairkan saldo yang tersedia di akun.

<b>1. Pastikan Saldo Cukup</b>
Cek saldo akun sebelum melakukan withdraw.

<b>2. Buka Withdraw</b>
Masuk ke menu 🏦 <b>Withdraw</b>.

<b>3. Pilih Metode</b>
Pilih metode pencairan yang tersedia, misalnya:
• DANA
• OVO
• GoPay
• ShopeePay
• Bank

⚠️ Metode yang tersedia mengikuti pengaturan sistem.

<b>4. Masukkan Data</b>
Masukkan:
💰 Nominal withdraw
👤 Nama pemilik
🔢 Nomor rekening/e-wallet

<b>5. Periksa Data</b>
Pastikan:
✔ Nama benar.
✔ Nomor benar.
✔ Nominal benar.

Jika sudah benar, kirim permintaan withdraw.

<b>Status Withdraw</b>
⏳ Pending — sedang diproses.
✅ Success — berhasil.
❌ Failed — gagal.

⚠️ <b>Penting</b>
Pastikan data pencairan benar.

Kesalahan nomor rekening/e-wallet dapat menyebabkan dana gagal diterima.

Jika mengalami masalah, hubungi admin melalui menu bantuan.
"""
    )
