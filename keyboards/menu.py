from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def _b(text, data=None, url=None):
    return InlineKeyboardButton(text=text, callback_data=data, url=url)


def home_kb(user_id: int, lang: str = "id", is_creator: bool = False):
    idn = lang == "id"
    return InlineKeyboardMarkup(inline_keyboard=[
        [_b("📤 Upfile" if idn else "📤 Upfile", "upfile"), _b("📥 Getfile" if idn else "📥 Getfile", "getfile")],
        [_b("🛍️ Marketplace", "marketplace"), _b("👤 Account" if idn else "👤 Account", "account")],
        [_b("📂 Menu Lainnya" if idn else "📂 More Menu", "menu_lainnya"), _b("❓ Help" if idn else "❓ Help", "help")],
    ])


def account_kb(lang="id", is_creator=False):
    idn = lang == "id"
    rows = [
        [_b("⚙️ Pengaturan" if idn else "⚙️ Settings", "account_settings")],
        [_b("🎨 Kreator" if idn else "🎨 Creator", "creator"), _b("💎 VIP", "vvip")],
    ]
    if is_creator:
        rows.append([_b("💸 Withdraw" if idn else "💸 Withdraw", "withdraw")])
    rows.append([_b("⬅️ Kembali" if idn else "⬅️ Back", "home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def settings_kb(lang="id"):
    idn = lang == "id"
    return InlineKeyboardMarkup(inline_keyboard=[
        [_b("💳 Setting Withdraw" if idn else "💳 Withdraw Settings", "ewallet")],
        [_b("🌐 Bahasa" if idn else "🌐 Language", "change_language")],
        [_b("⬅️ Account" if idn else "⬅️ Account", "account")],
    ])


def other_menu_kb(lang="id"):
    idn = lang == "id"
    return InlineKeyboardMarkup(inline_keyboard=[
        [_b("⭐ Channel Review Semua Media" if idn else "⭐ All Media Review Channel", url=None, data="channel_review")],
        [_b("🔔 Channel Notifikasi" if idn else "🔔 Notification Channel", url=None, data="channel_notification")],
        [_b("💳 Channel Transaksi" if idn else "💳 Transaction Channel", url=None, data="channel_transaction")],
        [_b("📦 Kumpulkan Semua Code" if idn else "📦 Collect All Codes", "collect_all_codes")],
        [_b("❓ Help", "help")],
        [_b("⬅️ Kembali" if idn else "⬅️ Back", "home")],
    ])
