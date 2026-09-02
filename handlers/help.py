from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from database import get_pool

router = Router()

def kb(rows):
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=t, callback_data=d) for t,d in row] for row in rows])

async def lang_of(user_id: int) -> str:
    pool = await get_pool()
    return (await pool.fetchval('SELECT language FROM users WHERE user_id=$1', user_id)) or 'id'

@router.callback_query(F.data == 'help')
async def help_menu(call: CallbackQuery):
    lang = await lang_of(call.from_user.id)
    if lang == 'en':
        text = ('❓ <b>HELP CENTER</b>\n━━━━━━━━━━━━━━━━━━\n\n'
                '<b>What is this bot?</b>\nA Telegram marketplace to upload, store, share, buy and sell Telegram codes/media safely and conveniently.\n\n'
                '<b>What can you do?</b>\n📤 Upload & create a code\n🛍 Browse and buy codes\n💰 Sell your own code\n🎁 Earn free unlock progress from real purchases\n⭐ Rate, like/dislike and review media\n❤️ Save favorites\n👤 Manage your account and balance\n💎 Upgrade VIP/VVIP\n🤝 Invite friends with referral\n\nChoose a guide below.')
        rows = [[('📤 Upload & Sell','help_upload'),('🛍 Buy Code','help_buy')],
                [('🎁 Free Unlock 3/3','help_free'),('⭐ Like / Rating / Review','help_reaction')],
                [('💰 Earnings & Referral','help_earn'),('💎 VIP / VVIP','help_vip')],
                [('🔐 Safety & Limits','help_safety')],[('🌐 Language','change_language')],[('🏠 Home','home')]]
    else:
        text = ('❓ <b>PUSAT BANTUAN</b>\n━━━━━━━━━━━━━━━━━━\n\n'
                '<b>Apa itu bot ini?</b>\nMarketplace Telegram untuk upload, menyimpan, membagikan, membeli, dan menjual code/media dengan cara yang mudah dipahami.\n\n'
                '<b>Apa yang bisa dilakukan?</b>\n📤 Upload & buat code\n🛍 Cari dan beli code\n💰 Jual code sendiri\n🎁 Dapatkan akses gratis dari progres pembelian nyata\n⭐ Like, dislike, rating, dan review\n❤️ Simpan favorit\n👤 Kelola akun dan saldo\n💎 Upgrade VIP/VVIP\n🤝 Undang teman lewat referral\n\nPilih panduan di bawah.')
        rows = [[('📤 Upload & Jual','help_upload'),('🛍 Beli Code','help_buy')],
                [('🎁 Buka Gratis 3/3','help_free'),('⭐ Like / Rating / Review','help_reaction')],
                [('💰 Cuan & Referral','help_earn'),('💎 VIP / VVIP','help_vip')],
                [('🔐 Keamanan & Batasan','help_safety')],[('🌐 Bahasa','change_language')],[('🏠 Home','home')]]
    await call.message.edit_text(text, parse_mode='HTML', reply_markup=kb(rows))
    await call.answer()

GUIDES = {
'id': {
'help_upload': ('📤 <b>UPLOAD & JUAL CODE</b>\n━━━━━━━━━━━━━━━━━━\n\n'
'1️⃣ Tekan <b>Upload File</b>.\n2️⃣ Kirim media yang ingin disimpan.\n3️⃣ Tekan <b>STOP & SAVE</b> setelah selesai.\n4️⃣ Isi judul, kategori, deskripsi, dan tipe FREE/PAID.\n5️⃣ Jika PAID, tentukan harga sesuai ketentuan bot.\n6️⃣ Bot membuat <b>CODE</b> otomatis.\n\n<b>Keuntungan seller:</b> code bisa dipromosikan di marketplace, pembeli dapat membuka media setelah pembayaran berhasil, dan statistik seperti view, like, dislike, rating, review, serta penjualan dapat dipantau.\n\n💡 Gunakan judul/deskripsi yang jujur dan jelas agar calon pembeli mudah memahami isi code.'),
'help_buy': ('🛍 <b>CARA BELI CODE</b>\n━━━━━━━━━━━━━━━━━━\n\n1️⃣ Buka Marketplace.\n2️⃣ Pilih code yang menarik.\n3️⃣ Periksa harga, jumlah media, terjual, like/dislike, rating, dan review.\n4️⃣ Tekan <b>Beli</b>.\n5️⃣ Selesaikan pembayaran.\n6️⃣ Setelah pembayaran terkonfirmasi, akses media diberikan.\n\nJika QR otomatis bermasalah pada pembayaran tertentu, gunakan metode/QR manual yang disediakan bot.'),
'help_free': ('🎁 <b>BUKA CODE GRATIS — PROGRESS 3/3</b>\n━━━━━━━━━━━━━━━━━━\n\nFitur ini dibuat agar kamu bisa mendapatkan akses gratis dengan membantu seller mendapatkan pembeli.\n\n📈 Ada <b>3 progress</b>. Kamu membagikan code terlebih dahulu. Progress <b>bertambah hanya ketika ada pembelian yang benar-benar berhasil</b> dari code tersebut, bukan sekadar menekan tombol share.\n\n1/3 → 1 pembelian\n2/3 → 2 pembelian\n3/3 → 3 pembelian\n\nSetelah 3/3, code yang kamu promosikan dapat dibuka tanpa membayar. Sistem mencatat progres per pengguna dan per code agar tidak tercampur.'),
'help_reaction': ('⭐ <b>LIKE, DISLIKE, RATING & REVIEW</b>\n━━━━━━━━━━━━━━━━━━\n\nSaat membuka detail media, kamu bisa memilih 👍 Suka atau 👎 Tidak suka. Satu user hanya memiliki satu reaksi aktif dan bisa menggantinya.\n\n⭐ <b>Rating</b> membantu menunjukkan kualitas berdasarkan penilaian pengguna.\n💬 <b>Review</b> digunakan untuk menulis pengalaman/masukan. Review dapat diperbarui oleh pemilik akun dan ditampilkan pada detail code.\n\nMarketplace memakai data tersebut untuk membantu pengguna melihat code yang paling disukai, paling banyak mendapat masukan, dan memiliki reputasi terbaik.'),
'help_earn': ('💰 <b>CUAN & REFERRAL</b>\n━━━━━━━━━━━━━━━━━━\n\n💵 <b>Penjualan:</b> seller mendapatkan pendapatan sesuai aturan komisi bot.\n🤝 <b>Referral:</b> bagikan link referral pribadi. Jika user baru masuk melalui link tersebut dan memenuhi syarat sistem, referral tercatat dan reward diberikan sesuai program aktif.\n\nGunakan tombol <b>Bagikan Referral</b> agar link mudah dikirim ke Telegram. Hindari spam dan kirim hanya kepada orang yang memang ingin menggunakan bot.'),
'help_vip': ('💎 <b>VIP / VVIP</b>\n━━━━━━━━━━━━━━━━━━\n\nVIP/VVIP memberikan akses premium sesuai paket aktif.\n\nJika QR otomatis gagal/error, pilih <b>QR Manual</b>. Setelah membayar, tekan <b>Saya Sudah Bayar</b>. Admin akan menerima notifikasi untuk memeriksa pembayaran.\n\n✅ APPROVE → paket aktif dan user menerima notifikasi.\n❌ FAILED → admin wajib memberikan alasan, misalnya pembayaran belum lunas, nominal tidak sesuai, atau pembayaran belum masuk. Alasan dikirim ke user agar jelas langkah berikutnya.'),
'help_safety': ('🔐 <b>KEAMANAN & PENGGUNAAN AMAN</b>\n━━━━━━━━━━━━━━━━━━\n\nBot menerapkan pembatasan dan pemrosesan bertahap untuk mengurangi spam, duplikasi transaksi, dan beban Telegram.\n\n⚠️ Tidak ada bot yang bisa menjamin 100% bebas banned/flood karena keputusan akhir tetap milik Telegram.\n\nAgar aman:\n• Jangan spam command/callback berulang-ulang.\n• Jangan broadcast ke pengguna tanpa izin.\n• Jangan upload konten ilegal atau melanggar hak cipta.\n• Jangan melakukan manipulasi pembayaran, like, rating, review, atau referral.\n• Gunakan tombol resmi bot dan tunggu proses selesai sebelum menekan ulang.'),
},
'en': {
'help_upload': ('📤 <b>UPLOAD & SELL CODE</b>\n━━━━━━━━━━━━━━━━━━\n\n1️⃣ Tap <b>Upload File</b>.\n2️⃣ Send the media you want to store.\n3️⃣ Press <b>STOP & SAVE</b> when finished.\n4️⃣ Set title, category, description and FREE/PAID type.\n5️⃣ For PAID, set the price allowed by the bot.\n6️⃣ The bot creates a unique <b>CODE</b>.\n\n<b>Seller benefits:</b> promote your code in the marketplace and track views, likes, dislikes, ratings, reviews and sales. Buyers receive access after successful payment.'),
'help_buy': ('🛍 <b>HOW TO BUY A CODE</b>\n━━━━━━━━━━━━━━━━━━\n\n1️⃣ Open Marketplace.\n2️⃣ Choose a code.\n3️⃣ Check price, media count, sales, likes/dislikes, rating and reviews.\n4️⃣ Tap <b>Buy</b>.\n5️⃣ Complete payment.\n6️⃣ After confirmation, the media access is delivered.\n\nIf automatic QR fails, use the manual QR/payment option shown by the bot.'),
'help_free': ('🎁 <b>FREE CODE UNLOCK — 3/3 PROGRESS</b>\n━━━━━━━━━━━━━━━━━━\n\nShare the code first to help the seller get real buyers. Progress increases <b>only after a real successful purchase</b>, not simply because the share button was pressed.\n\n1/3 → 1 purchase\n2/3 → 2 purchases\n3/3 → 3 purchases\n\nAt 3/3, the code you promoted can be opened for free. Progress is tracked per user and per code.'),
'help_reaction': ('⭐ <b>LIKE, DISLIKE, RATING & REVIEW</b>\n━━━━━━━━━━━━━━━━━━\n\nOn a media detail page you can choose 👍 Like or 👎 Dislike. One user has one active reaction and can change it.\n\n⭐ <b>Rating</b> reflects user scoring.\n💬 <b>Review</b> lets users leave useful feedback and update their own review.\n\nMarketplace statistics use these signals to highlight popular and well-reviewed codes.'),
'help_earn': ('💰 <b>EARNINGS & REFERRAL</b>\n━━━━━━━━━━━━━━━━━━\n\n💵 <b>Sales:</b> sellers receive earnings according to the bot commission rules.\n🤝 <b>Referral:</b> share your personal referral link. Eligible new users are recorded and rewards are issued according to the active referral program.\n\nUse <b>Share Referral</b> and avoid unsolicited spam.'),
'help_vip': ('💎 <b>VIP / VVIP</b>\n━━━━━━━━━━━━━━━━━━\n\nVIP/VVIP provides premium access according to the active plan.\n\nIf automatic QR fails, choose <b>Manual QR</b>. After paying, tap <b>I Have Paid</b>. Admin receives a verification request.\n\n✅ APPROVE → the plan is activated and the user is notified.\n❌ FAILED → admin must enter a reason, such as incomplete payment, wrong amount, or payment not received. The reason is sent to the user.'),
'help_safety': ('🔐 <b>SAFETY & USAGE</b>\n━━━━━━━━━━━━━━━━━━\n\nThe bot uses throttling/step-by-step processing to reduce spam, duplicate transactions and excessive Telegram API load.\n\n⚠️ No bot can guarantee 100% protection from Telegram restrictions.\n\nFor safer use:\n• Do not spam commands or callbacks.\n• Do not broadcast without permission.\n• Do not upload illegal/copyright-infringing content.\n• Do not manipulate payment, likes, ratings, reviews or referrals.\n• Use the official buttons and wait for a process to finish before retrying.'),
}}

@router.callback_query(F.data.in_(list(GUIDES['id']) + list(GUIDES['en'])))
async def guide(call: CallbackQuery):
    lang = await lang_of(call.from_user.id)
    text = GUIDES[lang].get(call.data, GUIDES['id'][call.data])
    await call.message.edit_text(text, parse_mode='HTML', reply_markup=kb([[('⬅️ Kembali' if lang=='id' else '⬅️ Back','help')],[('🏠 Home','home')]]))
    await call.answer()
