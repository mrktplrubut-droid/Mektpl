from aiogram import Router, F
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from database import get_pool

router = Router()

class ReviewState(StatesGroup):
    waiting_text = State()

@router.callback_query(F.data.startswith('review:'))
async def review_start(call: CallbackQuery, state: FSMContext):
    code = call.data.split(':', 1)[1]
    pool = await get_pool()
    exists = await pool.fetchval('SELECT 1 FROM files WHERE code=$1', code)
    if not exists:
        return await call.answer('❌ Code tidak ditemukan.', show_alert=True)
    await state.update_data(review_code=code)
    await state.set_state(ReviewState.waiting_text)
    await call.message.edit_text(
        '💬 <b>TULIS REVIEW</b>\n\n'
        'Tulis pengalaman kamu tentang code/media ini.\n'
        'Review yang jelas membantu pembeli lain mengambil keputusan.\n\n'
        'Ketik <b>batal</b> untuk membatalkan.',
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text='⬅️ Batal', callback_data=f'market:{code}')
        ]])
    )
    await call.answer()

@router.message(ReviewState.waiting_text)
async def review_save(message: Message, state: FSMContext):
    text = (message.text or '').strip()
    data = await state.get_data()
    code = data.get('review_code')
    if not code:
        await state.clear()
        return await message.answer('❌ Sesi review berakhir. Silakan buka detail code lagi.')
    if text.lower() in {'batal', 'cancel'}:
        await state.clear()
        return await message.answer('↩️ Review dibatalkan.')
    if len(text) < 3:
        return await message.answer('⚠️ Review terlalu singkat. Tulis minimal 3 karakter.')
    text = text[:1000]
    pool = await get_pool()
    await pool.execute('''
        CREATE TABLE IF NOT EXISTS file_reviews (
            id BIGSERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL,
            file_code TEXT NOT NULL,
            review TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW(),
            UNIQUE(user_id, file_code)
        )
    ''')
    await pool.execute('''
        INSERT INTO file_reviews(user_id,file_code,review)
        VALUES($1,$2,$3)
        ON CONFLICT(user_id,file_code)
        DO UPDATE SET review=EXCLUDED.review, updated_at=NOW()
    ''', message.from_user.id, code, text)
    await pool.execute('''
        UPDATE files SET review_count=(SELECT COUNT(*) FROM file_reviews WHERE file_code=$1) WHERE code=$1
    ''', code)
    await state.clear()
    await message.answer('✅ Review berhasil disimpan. Terima kasih sudah membantu marketplace!')

@router.callback_query(F.data.startswith('reviews:'))
async def review_list(call: CallbackQuery):
    code = call.data.split(':', 1)[1]
    pool = await get_pool()
    rows = await pool.fetch('''
        SELECT user_id, review, created_at FROM file_reviews
        WHERE file_code=$1 ORDER BY created_at DESC LIMIT 10
    ''', code)
    if not rows:
        text = '💬 <b>REVIEW</b>\n\nBelum ada review untuk code ini.'
    else:
        parts = ['💬 <b>REVIEW TERBARU</b>', '━━━━━━━━━━━━━━━━━━']
        for i, row in enumerate(rows, 1):
            parts.append(f'\n<b>{i}.</b> User <code>{row["user_id"]}</code>\n{row["review"]}')
        text = '\n'.join(parts)
    await call.message.edit_text(text, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text='💬 Tulis Review', callback_data=f'review:{code}')
    ], [InlineKeyboardButton(text='⬅️ Kembali', callback_data=f'market:{code}')]]))
    await call.answer()

@router.callback_query(F.data.startswith('share:'))
async def share_code(call: CallbackQuery):
    code = call.data.split(':', 1)[1]
    pool = await get_pool()
    row = await pool.fetchrow('SELECT title FROM files WHERE code=$1', code)
    if not row:
        return await call.answer('❌ Code tidak ditemukan.', show_alert=True)
    me = await call.bot.get_me()
    from urllib.parse import quote
    target = f'https://t.me/{me.username}?start={code}'
    share_url = 'https://t.me/share/url?url=' + quote(target) + '&text=' + quote('🤖 Coba code Telegram ini dari Marketplace!')
    lang = await lang_of(call.from_user.id)
    text = ('📤 <b>BAGIKAN CODE</b>\n\nBagikan code ini ke teman/calon pembeli. Jika ada pembelian berhasil, progress gratis 3 tahap untuk code ini akan bertambah.'
            if lang == 'id' else
            '📤 <b>SHARE CODE</b>\n\nShare this code with friends/potential buyers. Every successful purchase increases the 3-step free-unlock progress for this code.')
    await call.message.edit_text(text, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='📤 Bagikan Sekarang' if lang=='id' else '📤 Share Now', url=share_url)],
        [InlineKeyboardButton(text='🎁 Cek Progress' if lang=='id' else '🎁 Check Progress', callback_data=f'freeopen:{code}')],
        [InlineKeyboardButton(text='⬅️ Kembali' if lang=='id' else '⬅️ Back', callback_data=f'market:{code}')]
    ]))
    await call.answer()

@router.callback_query(F.data == 'market_reviews')
async def market_reviews(call: CallbackQuery):
    lang = await lang_of(call.from_user.id)
    pool = await get_pool()
    rows = await pool.fetch('''
        SELECT f.code, f.title, COALESCE(f.review_count,0) review_count,
               COALESCE(f.rating,0) rating, COALESCE(f.sold,0) sold
        FROM files f WHERE COALESCE(f.review_count,0)>0
        ORDER BY review_count DESC, rating DESC, sold DESC LIMIT 20
    ''')
    if lang == 'en':
        text='💬 <b>MOST REVIEWED CODES</b>\n━━━━━━━━━━━━━━━━━━\n\n'
    else:
        text='💬 <b>CODE PALING BANYAK DIREVIEW</b>\n━━━━━━━━━━━━━━━━━━\n\n'
    if not rows:
        text += '📭 ' + ('No reviews yet.' if lang=='en' else 'Belum ada review.')
    rows_kb=[]
    for i,r in enumerate(rows,1):
        text += f'{i}. <b>{r["title"] or r["code"]}</b>\n💬 {r["review_count"]} review • ⭐ {float(r["rating"] or 0):.1f} • 🔥 {r["sold"]} sold\n\n'
        rows_kb.append([InlineKeyboardButton(text=f'💬 {str(r["title"] or r["code"])[:25]}', callback_data=f'market:{r["code"]}')])
    rows_kb.append([InlineKeyboardButton(text='⬅️ Marketplace' if lang=='id' else '⬅️ Marketplace', callback_data='marketplace')])
    await call.message.edit_text(text, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(inline_keyboard=rows_kb))
    await call.answer()
