from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from database import get_pool

router = Router()

@router.callback_query(F.data == 'free_codes')
async def free_codes(call: CallbackQuery):
    pool = await get_pool()
    lang = (await pool.fetchval('SELECT language FROM users WHERE user_id=$1', call.from_user.id)) or 'id'
    rows = await pool.fetch(
        'SELECT p.code, COALESCE(f.title,p.code) AS title, p.purchase_count, p.completed '
        'FROM free_code_progress p LEFT JOIN files f ON f.code=p.code '
        'WHERE p.user_id=$1 ORDER BY p.completed DESC, p.purchase_count DESC LIMIT 30',
        call.from_user.id
    )
    if lang == 'en':
        text = '🎁 <b>MY FREE CODE PROGRESS</b>\n━━━━━━━━━━━━━━━━━━\n\nShare a paid code first. Each successful purchase adds +1 progress. At 3/3 you can open it for free.\n\n'
    else:
        text = '🎁 <b>PROGRESS CODE GRATIS SAYA</b>\n━━━━━━━━━━━━━━━━━━\n\nBagikan code berbayar terlebih dahulu. Setiap pembelian berhasil menambah +1 progress. Saat 3/3 kamu bisa membukanya gratis.\n\n'
    buttons = []
    if not rows:
        text += '📭 ' + ('You have not promoted any code yet.' if lang == 'en' else 'Belum ada code yang kamu promosikan.')
    for row in rows:
        progress = int(row['purchase_count'] or 0)
        status = '🎉 3/3' if row['completed'] else f'📈 {progress}/3'
        text += f"• <b>{row['title']}</b> — {status}\n"
        buttons.append([InlineKeyboardButton(text=f'🎁 {str(row["title"])[:24]} • {progress}/3', callback_data=f'freeopen:{row["code"]}')])
    buttons += [[InlineKeyboardButton(text='🛍 Marketplace', callback_data='marketplace')], [InlineKeyboardButton(text='🏠 Home', callback_data='home')]]
    await call.message.edit_text(text, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await call.answer()
