from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from database import get_pool

router = Router()

async def home_kb(user_id: int):
    pool = await get_pool()
    lang = (await pool.fetchval("SELECT language FROM users WHERE user_id=$1", user_id)) or "id"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📤 Upload File" if lang=="id" else "📤 Upload", callback_data="upfile"), InlineKeyboardButton(text="📥 Get File" if lang=="id" else "📥 Get Code", callback_data="getfile")],
        [InlineKeyboardButton(text="👤 Akun" if lang=="id" else "👤 Account", callback_data="account"), InlineKeyboardButton(text="🛍️ Marketplace", callback_data="marketplace")],
        [InlineKeyboardButton(text="🎨 Kreator" if lang=="id" else "🎨 Creator", callback_data="creator"), InlineKeyboardButton(text="🎁 Code Free" if lang=="id" else "🎁 Free Codes", callback_data="free_codes")],
        [InlineKeyboardButton(text="📂 Menu Lainnya" if lang=="id" else "📂 More Menu", callback_data="menu_lainnya"), InlineKeyboardButton(text="❓ Bantuan" if lang=="id" else "❓ Help", callback_data="help")],
        [InlineKeyboardButton(text="🌐 Bahasa" if lang=="id" else "🌐 Language", callback_data="change_language")]
    ])

def other_menu_kb(lang="id"):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📦 Code", callback_data="code"), InlineKeyboardButton(text="💰 Ewallet", callback_data="ewallet")],
        [InlineKeyboardButton(text="💸 Tarik Saldo" if lang=="id" else "💸 Withdraw", callback_data="withdraw"), InlineKeyboardButton(text="📊 Marketplace", callback_data="marketplace")],
        [InlineKeyboardButton(text="📢 Info Channel", callback_data="channel")],
        [InlineKeyboardButton(text="⬅️ Kembali" if lang=="id" else "⬅️ Back", callback_data="home")]
    ])

@router.callback_query(F.data == "menu_lainnya")
async def menu_lainnya(callback: CallbackQuery):
    pool=await get_pool(); lang=(await pool.fetchval("SELECT language FROM users WHERE user_id=$1", callback.from_user.id)) or "id"
    await callback.message.edit_reply_markup(reply_markup=other_menu_kb(lang))
    await callback.answer()

@router.callback_query(F.data == "home")
async def back_home(callback: CallbackQuery):
    await callback.message.edit_reply_markup(reply_markup=await home_kb(callback.from_user.id))
    await callback.answer()
