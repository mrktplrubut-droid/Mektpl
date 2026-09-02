import math
from aiogram import Router, F
from aiogram.types import CallbackQuery, Message, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from database import get_pool
from utils.user_lang import get_user_language

router = Router()

SERVERS = {
    "1": {"id": "1", "id_name": "Server 1 — Media Umum", "en_name": "Server 1 — General Media"},
    "2": {"id": "2", "id_name": "Server 2 — Media Remaja Non-Seksual", "en_name": "Server 2 — Non-Sexual Teen Media"},
    "3": {"id": "3", "id_name": "Server 3 — Media Dewasa 18+ Non-Eksplisit", "en_name": "Server 3 — 18+ Non-Explicit Media"},
}

class MarketSearch(StatesGroup):
    waiting = State()

def price(v):
    return f"Rp {int(v or 0):,}".replace(",", ".")

def server_name(server, lang):
    s = SERVERS.get(str(server), SERVERS["1"])
    return s["en_name"] if lang == "en" else s["id_name"]

async def render_server(call, server, sort="new", search=None):
    lang = await get_user_language(call.from_user.id)
    pool = await get_pool()
    server = str(server)
    if server not in SERVERS:
        return await call.answer("Invalid server." if lang == "en" else "Server tidak valid.", show_alert=True)
    where = ["COALESCE(market_server,'1')=$1"]
    args = [server]
    if search:
        where.append("(title ILIKE $2 OR code ILIKE $2 OR COALESCE(description,'') ILIKE $2)")
        args.append(f"%{search[:80]}%")
    order = {
        "best": "COALESCE(sold,0) DESC, COALESCE(rating,0) DESC, created_at DESC",
        "top": "(COALESCE(views,0)+COALESCE(sold,0)*10+COALESCE(favorite_count,0)*5+COALESCE(rating,0)*COALESCE(review_count,0)*3) DESC, created_at DESC",
        "rating": "COALESCE(rating,0) DESC, COALESCE(review_count,0) DESC, COALESCE(sold,0) DESC",
        "favorite": "COALESCE(favorite_count,0) DESC, COALESCE(sold,0) DESC, created_at DESC",
        "new": "created_at DESC",
    }.get(sort, "created_at DESC")
    rows = await pool.fetch(f"""
        SELECT code,title,price,media_count,created_at,
               COALESCE(sold,0) sold, COALESCE(views,0) views,
               COALESCE(rating,0) rating, COALESCE(review_count,0) review_count,
               COALESCE(favorite_count,0) favorite_count
        FROM files WHERE {' AND '.join(where)}
        ORDER BY {order} LIMIT 20
    """, *args)
    labels = {
        "id": ["🛒 MARKETPLACE", "Pilih server terlebih dahulu:", "🔍 Cari File", "🔥 Terlaris", "🏆 Top 10", "🆕 Terbaru", "⭐ Rating", "❤️ Favorit", "⬅️ Kembali"],
        "en": ["🛒 MARKETPLACE", "Choose a server first:", "🔍 Search Files", "🔥 Best Sellers", "🏆 Top 10", "🆕 Newest", "⭐ Top Rated", "❤️ Favorites", "⬅️ Back"],
    }[lang]
    text = f"<b>{labels[0]}</b>\n━━━━━━━━━━━━━━━━━━\n\n{labels[1]}\n\n<b>{server_name(server,lang)}</b>\n\n"
    if search:
        text += ("🔎 Search: " if lang == "en" else "🔎 Pencarian: ") + f"<b>{search}</b>\n\n"
    if not rows:
        text += "📭 No files found." if lang == "en" else "📭 Belum ada file di server ini."
    else:
        for i,r in enumerate(rows,1):
            text += f"{i}. <b>{r['title'] or r['code']}</b>\n💰 {price(r['price']) if r['price'] else ('Free' if lang=='en' else 'Gratis')} • 📁 {r['media_count'] or 0}\n🔥 {r['sold']} • ⭐ {float(r['rating'] or 0):.1f} ({r['review_count']}) • ❤️ {r['favorite_count']}\n\n"
    kb=[]
    for r in rows:
        kb.append([InlineKeyboardButton(text=f"📦 {str(r['title'] or r['code'])[:28]}", callback_data=f"market:{r['code']}")])
    kb += [
        [InlineKeyboardButton(text=labels[2], callback_data=f"mkt:search:{server}"), InlineKeyboardButton(text=labels[3], callback_data=f"mkt:list:{server}:best")],
        [InlineKeyboardButton(text=labels[4], callback_data=f"mkt:list:{server}:top"), InlineKeyboardButton(text=labels[5], callback_data=f"mkt:list:{server}:new")],
        [InlineKeyboardButton(text=labels[6], callback_data=f"mkt:list:{server}:rating"), InlineKeyboardButton(text=labels[7], callback_data=f"mkt:list:{server}:favorite")],
        [InlineKeyboardButton(text="🔄 Servers", callback_data="marketplace") if lang=="en" else InlineKeyboardButton(text="🔄 Pilih Server", callback_data="marketplace")]
    ]
    await call.message.edit_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@router.callback_query(F.data == "marketplace")
async def marketplace_menu(call: CallbackQuery):
    lang = await get_user_language(call.from_user.id)
    text = ("🛒 <b>MARKETPLACE</b>\n━━━━━━━━━━━━━━━━━━\n\nChoose a server:" if lang=="en" else "🛒 <b>MARKETPLACE</b>\n━━━━━━━━━━━━━━━━━━\n\nPilih server:")
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=server_name("1",lang), callback_data="mkt:server:1")],
        [InlineKeyboardButton(text=server_name("2",lang), callback_data="mkt:server:2")],
        [InlineKeyboardButton(text=server_name("3",lang), callback_data="mkt:server:3")],
        [InlineKeyboardButton(text="🏠 Home" if lang=="id" else "🏠 Home", callback_data="home")]
    ])
    await call.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    await call.answer()

@router.callback_query(F.data.startswith("mkt:server:"))
async def select_server(call: CallbackQuery):
    await call.answer()
    await render_server(call, call.data.rsplit(":",1)[1])

@router.callback_query(F.data.startswith("mkt:list:"))
async def list_server(call: CallbackQuery):
    _,_,server,sort = call.data.split(":",3)
    await call.answer()
    await render_server(call, server, sort)

@router.callback_query(F.data.startswith("mkt:search:"))
async def search_start(call: CallbackQuery, state: FSMContext):
    lang=await get_user_language(call.from_user.id); server=call.data.rsplit(":",1)[1]
    await state.update_data(market_server=server); await state.set_state(MarketSearch.waiting)
    await call.message.edit_text("🔍 <b>SEARCH FILES</b>\n\nSend title, code, or keyword:" if lang=="en" else "🔍 <b>CARI FILE</b>\n\nKirim judul, code, atau kata kunci:", parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Cancel" if lang=="en" else "❌ Batal", callback_data=f"mkt:server:{server}")]]))
    await call.answer()

@router.message(MarketSearch.waiting)
async def search_process(message: Message, state: FSMContext):
    data=await state.get_data(); server=str(data.get("market_server","1")); q=(message.text or "").strip()
    await state.clear()
    # Message cannot be edited; create a lightweight callback-like renderer.
    lang=await get_user_language(message.from_user.id); pool=await get_pool()
    rows=await pool.fetch("""SELECT code,title,price,media_count,COALESCE(sold,0)sold,COALESCE(rating,0)rating,COALESCE(review_count,0)review_count,COALESCE(favorite_count,0)favorite_count FROM files WHERE COALESCE(market_server,'1')=$1 AND (title ILIKE $2 OR code ILIKE $2 OR COALESCE(description,'') ILIKE $2) ORDER BY created_at DESC LIMIT 20""",server,f"%{q[:80]}%")
    text=("🔍 <b>SEARCH RESULTS</b>" if lang=="en" else "🔍 <b>HASIL PENCARIAN</b>")+f"\n━━━━━━━━━━━━━━━━━━\n\n<b>{q}</b>\n\n"
    if not rows: text += "📭 No files found." if lang=="en" else "📭 File tidak ditemukan."
    kb=[]
    for r in rows:
        text += f"📦 <b>{r['title'] or r['code']}</b>\n💰 {price(r['price']) if r['price'] else ('Free' if lang=='en' else 'Gratis')} • ⭐ {float(r['rating'] or 0):.1f} • 🔥 {r['sold']}\n\n"
        kb.append([InlineKeyboardButton(text=f"📦 {str(r['title'] or r['code'])[:28]}", callback_data=f"market:{r['code']}")])
    kb.append([InlineKeyboardButton(text="⬅️ Back" if lang=="en" else "⬅️ Kembali", callback_data=f"mkt:server:{server}")])
    await message.answer(text,parse_mode="HTML",reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
