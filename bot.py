from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties

from config import BOT_TOKEN

from middlewares.ban import BanMiddleware
from middlewares.maintenance import MaintenanceMiddleware


# =========================
# BOT INIT
# =========================

bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(
        parse_mode="HTML"
    )
)

dp = Dispatcher()


# =========================
# MIDDLEWARE
# =========================

dp.message.middleware(
    BanMiddleware()
)

dp.callback_query.middleware(
    BanMiddleware()
)

dp.message.middleware(
    MaintenanceMiddleware()
)

dp.callback_query.middleware(
    MaintenanceMiddleware()
)


# =========================
# ROUTERS IMPORT
# =========================

from handlers.start import router as start_router
from handlers.check_sub import router as check_sub_router

from handlers.upfile import router as upfile_router
from handlers.getfile import router as getfile_router
from handlers.page import router as page_router
from handlers.open_menu import router as open_menu_router

from handlers.top import router as top_router
from handlers.code import router as code_router

from handlers.search_code import router as search_router
from handlers.price_code import router as price_router
from handlers.new_code import router as new_code_router
from handlers.category_code import router as category_router

from handlers.channel import router as channel_router
from handlers.account import router as account_router
from handlers.my_code import router as my_code_router
from handlers.help import router as help_router
from handlers.market_detail import router as market_detail_router
from handlers.myfile import router as myfile_router
from handlers.delete_file import router as delete_file_router
from handlers.edit_price import router as edit_price_router
from handlers.ewallet import router as ewallet_router

from handlers.pay import router as pay_router
from handlers.cancel import router as cancel_router

from handlers.withdraw import (
    withdraw_router,
    withdraw_confirm_router
)

from handlers.admin import router as admin_router
from handlers.notify import router as notify_router
from handlers.marketplace import router as marketplace_router


# =========================
# REGISTER ROUTERS
# =========================
# BASIC
dp.include_router(start_router)
dp.include_router(check_sub_router)

# FILE SYSTEM
dp.include_router(upfile_router)
dp.include_router(getfile_router)
dp.include_router(page_router)
dp.include_router(open_menu_router)

# STORE
dp.include_router(top_router)
dp.include_router(code_router)

# SEARCH
dp.include_router(channel_router)
dp.include_router(search_router)
dp.include_router(price_router)
dp.include_router(category_router)
dp.include_router(new_code_router)

# ACCOUNT
dp.include_router(account_router)
dp.include_router(my_code_router)
dp.include_router(help_router)
dp.include_router(market_detail_router)
dp.include_router(myfile_router)
dp.include_router(delete_file_router)
dp.include_router(edit_price_router)
dp.include_router(ewallet_router)

# PAYMENT
dp.include_router(pay_router)
dp.include_router(cancel_router)

# WITHDRAW
dp.include_router(withdraw_router)
dp.include_router(withdraw_confirm_router)

# ADMIN
dp.include_router(admin_router)

# MARKETPLACE
dp.include_router(marketplace_router)

# NOTIFICATION
dp.include_router(notify_router)
