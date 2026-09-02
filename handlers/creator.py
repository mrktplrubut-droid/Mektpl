import logging
from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from database import get_pool
from config import ADMIN_IDS, MANUAL_QR_FILE_ID
from utils.user_lang import get_user_language

router=Router(); logger=logging.getLogger(__name__)
CREATOR_PRICE=150_000
CREATOR_GROUP="https://t.me/+qo0L89j12hA1NTNl"

def rp(v): return f"Rp {int(v):,}".replace(",",".")

@router.callback_query(F.data=="creator")
async def creator_info(call:CallbackQuery):
    lang=await get_user_language(call.from_user.id); pool=await get_pool()
    u=await pool.fetchrow("SELECT is_creator,creator_status FROM users WHERE user_id=$1",call.from_user.id)
    approved=bool(u and u["is_creator"] and u["creator_status"]=="approved")
    pending=bool(u and u["creator_status"]=="pending")
    if approved:
        text=("🎨 <b>CREATOR</b>\n━━━━━━━━━━━━━━━━━━\n\n✅ Account verified.\n\n💰 You receive 70% of successful sales.\n💳 Withdraw is available after sales.\n📊 Manage paid media, balance, sales and statistics." if lang=="en" else "🎨 <b>KREATOR</b>\n━━━━━━━━━━━━━━━━━━\n\n✅ Akun sudah terverifikasi.\n\n💰 Kamu menerima 70% dari penjualan berhasil.\n💳 Withdraw tersedia dari saldo hasil penjualan.\n📊 Kelola media berbayar, saldo, penjualan, dan statistik.")
        kb=[[InlineKeyboardButton(text="📊 Creator Dashboard" if lang=="en" else "📊 Dashboard Kreator",callback_data="creator_dashboard")],[InlineKeyboardButton(text="📤 Upload" if lang=="en" else "📤 Upload",callback_data="upfile")],[InlineKeyboardButton(text="💸 Withdraw",callback_data="withdraw")],[InlineKeyboardButton(text="🛒 Marketplace",callback_data="marketplace")],[InlineKeyboardButton(text="👥 Creator Group",callback_data="creator_group")]]
    elif pending:
        text=("⏳ <b>CREATOR VERIFICATION</b>\n\nYour payment/verification is pending admin approval." if lang=="en" else "⏳ <b>VERIFIKASI KREATOR</b>\n\nPembayaran/verifikasi kamu sedang menunggu persetujuan admin.")
        kb=[[InlineKeyboardButton(text="🔄 Check Status" if lang=="en" else "🔄 Cek Status",callback_data="creator")],[InlineKeyboardButton(text="🏠 Home",callback_data="home")]]
    else:
        text=(f"🎨 <b>BECOME A CREATOR</b>\n━━━━━━━━━━━━━━━━━━\n\n💳 Verification fee: <b>{rp(CREATOR_PRICE)}</b>\n\nAfter admin approval you can upload paid media, earn 70% from sales, view your paid media and withdraw your balance." if lang=="en" else f"🎨 <b>MENJADI KREATOR</b>\n━━━━━━━━━━━━━━━━━━\n\n💳 Biaya verifikasi: <b>{rp(CREATOR_PRICE)}</b>\n\nSetelah disetujui admin, kamu dapat upload media berbayar, memperoleh 70% dari penjualan, melihat semua media berbayar, dan melakukan withdraw saldo.")
        kb=[[InlineKeyboardButton(text="💳 Bayar Rp 150.000" if lang=="id" else "💳 Pay Rp 150,000",callback_data="creator_pay")],[InlineKeyboardButton(text="🏠 Home",callback_data="home")]]
    await call.message.edit_text(text,parse_mode="HTML",reply_markup=InlineKeyboardMarkup(inline_keyboard=kb)); await call.answer()

@router.callback_query(F.data=="creator_pay")
async def creator_pay(call:CallbackQuery):
    pool=await get_pool()
    u=await pool.fetchrow("SELECT is_creator,creator_status FROM users WHERE user_id=$1",call.from_user.id)
    if u and u["is_creator"] and u["creator_status"]=="approved": return await call.answer("Already verified.",show_alert=True)
    pending=await pool.fetchrow("SELECT id FROM creator_payments WHERE user_id=$1 AND status='pending' ORDER BY id DESC LIMIT 1",call.from_user.id)
    if pending: return await call.answer("Masih ada pembayaran kreator yang menunggu approval admin.",show_alert=True)
    tx=await pool.fetchrow("INSERT INTO creator_payments(user_id,amount,status) VALUES($1,$2,'pending') RETURNING id",call.from_user.id,CREATOR_PRICE)
    lang=await get_user_language(call.from_user.id)
    caption=(f"🎨 <b>CREATOR VERIFICATION</b>\n━━━━━━━━━━━━━━\n\n💰 Amount: <b>{rp(CREATOR_PRICE)}</b>\n🧾 ID: <code>CR-{tx['id']}</code>\n\nScan the QR, pay exactly the amount, then tap <b>I HAVE PAID</b>." if lang=="en" else f"🎨 <b>VERIFIKASI KREATOR</b>\n━━━━━━━━━━━━━━\n\n💰 Nominal: <b>{rp(CREATOR_PRICE)}</b>\n🧾 ID: <code>CR-{tx['id']}</code>\n\nScan QR, bayar sesuai nominal, lalu tekan <b>SAYA SUDAH BAYAR</b>.")
    kb=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅ Saya Sudah Bayar" if lang=="id" else "✅ I Have Paid",callback_data=f"creator_check:{tx['id']}")],[InlineKeyboardButton(text="🔙 Kembali",callback_data="creator")]])
    try: await call.message.delete()
    except: pass
    await call.message.answer_photo(MANUAL_QR_FILE_ID,caption=caption,parse_mode="HTML",reply_markup=kb); await call.answer()

@router.callback_query(F.data.startswith("creator_check:"))
async def creator_check(call:CallbackQuery):
    tx_id=int(call.data.rsplit(":",1)[1]); pool=await get_pool()
    tx=await pool.fetchrow("SELECT * FROM creator_payments WHERE id=$1 AND user_id=$2 AND status='pending'",tx_id,call.from_user.id)
    if not tx: return await call.answer("Transaksi tidak ditemukan atau sudah diproses.",show_alert=True)
    kb=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅ APPROVE",callback_data=f"creator_approve_pay:{tx_id}"),InlineKeyboardButton(text="❌ REJECT",callback_data=f"creator_reject_pay:{tx_id}")]])
    text=f"🎨 <b>CREATOR PAYMENT</b>\n\n👤 User: <code>{tx['user_id']}</code>\n💰 Amount: <b>{rp(tx['amount'])}</b>\n🧾 ID: <code>CR-{tx_id}</code>\n\nCheck payment and approve/reject."
    for admin in ADMIN_IDS:
        try: await call.bot.send_message(admin,text,parse_mode="HTML",reply_markup=kb)
        except Exception: logger.exception("creator admin notify")
    await call.message.answer("✅ Permintaan verifikasi sudah dikirim ke admin. Tunggu approval."); await call.answer()

@router.callback_query(F.data.startswith("creator_approve_pay:"))
async def creator_approve_pay(call:CallbackQuery):
    if call.from_user.id not in ADMIN_IDS: return await call.answer("Not allowed.",show_alert=True)
    tx_id=int(call.data.rsplit(":",1)[1]); pool=await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            tx=await conn.fetchrow("UPDATE creator_payments SET status='approved',admin_id=$1,reviewed_at=NOW() WHERE id=$2 AND status='pending' RETURNING *",call.from_user.id,tx_id)
            if not tx: return await call.answer("Sudah diproses.",show_alert=True)
            await conn.execute("UPDATE users SET is_creator=TRUE,creator_status='approved',creator_verified_at=NOW(),updated_at=NOW() WHERE user_id=$1",tx['user_id'])
    try: await call.bot.send_message(tx['user_id'],f"🎉 <b>AKUN KREATOR AKTIF!</b>\n\nKamu resmi menjadi Kreator.\n💰 Pendapatan penjualan: <b>70%</b>.\n\nGabung group kreator untuk bimbingan admin:\n{CREATOR_GROUP}",parse_mode="HTML")
    except: logger.exception("creator approval notify")
    await call.message.edit_text(call.message.text+"\n\n✅ <b>APPROVED</b>",parse_mode="HTML"); await call.answer("Creator approved.")

@router.callback_query(F.data.startswith("creator_reject_pay:"))
async def creator_reject_pay(call:CallbackQuery):
    if call.from_user.id not in ADMIN_IDS: return await call.answer("Not allowed.",show_alert=True)
    tx_id=int(call.data.rsplit(":",1)[1]); pool=await get_pool()
    tx=await pool.fetchrow("UPDATE creator_payments SET status='rejected',admin_id=$1,reason='Payment not verified',reviewed_at=NOW() WHERE id=$2 AND status='pending' RETURNING *",call.from_user.id,tx_id)
    if not tx: return await call.answer("Sudah diproses.",show_alert=True)
    try: await call.bot.send_message(tx['user_id'],"❌ Pembayaran kreator belum disetujui admin. Silakan periksa pembayaran dan coba kembali.")
    except: pass
    await call.message.edit_text(call.message.text+"\n\n❌ <b>REJECTED</b>",parse_mode="HTML"); await call.answer("Rejected.")

@router.callback_query(F.data=="creator_group")
async def creator_group(call:CallbackQuery):
    await call.answer(); await call.message.answer("👥 Group Kreator:\n"+CREATOR_GROUP)

@router.callback_query(F.data=="creator_dashboard")
async def creator_dashboard(call:CallbackQuery):
    pool=await get_pool(); uid=call.from_user.id
    u=await pool.fetchrow("SELECT is_creator,creator_status,balance,total_earn FROM users WHERE user_id=$1",uid)
    if not (u and u['is_creator'] and u['creator_status']=='approved'): return await call.answer("Khusus Kreator terverifikasi.",show_alert=True)
    stats=await pool.fetchrow("SELECT COUNT(*) total,COALESCE(SUM(sold),0) sold FROM files WHERE owner_id=$1 AND is_paid=TRUE",uid)
    lang=await get_user_language(uid)
    text=(f"📊 <b>CREATOR DASHBOARD</b>\n\n💰 Balance: <b>{rp(u['balance'])}</b>\n💵 Total Earned: <b>{rp(u['total_earn'])}</b>\n📦 Paid Media: <b>{stats['total']}</b>\n🔥 Sales: <b>{stats['sold']}</b>" if lang=='en' else f"📊 <b>DASHBOARD KREATOR</b>\n\n💰 Saldo: <b>{rp(u['balance'])}</b>\n💵 Total Pendapatan: <b>{rp(u['total_earn'])}</b>\n📦 Media Berbayar: <b>{stats['total']}</b>\n🔥 Terjual: <b>{stats['sold']}</b>")
    kb=[[InlineKeyboardButton(text="💸 Withdraw",callback_data="withdraw")],[InlineKeyboardButton(text="📦 Media Berbayar",callback_data="creator_paid_files")],[InlineKeyboardButton(text="⬅️ Creator",callback_data="creator")]]
    await call.message.edit_text(text,parse_mode="HTML",reply_markup=InlineKeyboardMarkup(inline_keyboard=kb)); await call.answer()

@router.callback_query(F.data=="creator_paid_files")
async def creator_paid_files(call:CallbackQuery):
    pool=await get_pool(); rows=await pool.fetch("SELECT code,title,price,COALESCE(sold,0)sold,COALESCE(market_server,'1') server FROM files WHERE owner_id=$1 AND is_paid=TRUE ORDER BY created_at DESC LIMIT 30",call.from_user.id)
    text="📦 <b>MEDIA BERBAYAR</b>\n━━━━━━━━━━━━━━\n\n"+("\n".join(f"• <code>{r['code']}</code> — {r['title'] or 'File'} — {rp(r['price'])} — 🔥 {r['sold']}" for r in rows) if rows else "Belum ada media berbayar.")
    await call.message.edit_text(text,parse_mode="HTML",reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Dashboard",callback_data="creator_dashboard")]])); await call.answer()
