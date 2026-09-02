import os
from dotenv import load_dotenv
load_dotenv()
# =========================
# GENERAL
# =========================
TIMEZONE = "Asia/Jakarta"
# =========================
# BOT
# =========================
BOT_TOKEN = os.getenv("BOT_TOKEN")
BOT_USERNAME = (
    os.getenv("BOT_USERNAME", "mktplbot")
    .lstrip("@")
    .strip()
)
BOT_URL = f"https://t.me/{BOT_USERNAME}"
# =========================
# DATABASE
# =========================
DATABASE_URL = os.getenv("DATABASE_URL")
STORAGE_CHANNEL_ID = int(
    os.getenv("STORAGE_CHANNEL_ID", "0")
)
# =========================
# PAYMENT
# =========================
# -------------------------
# BayarGG (lama)
# -------------------------
BAYARGG_API_KEY = os.getenv(
    "BAYARGG_API_KEY"
)
BAYARGG_MERCHANT = os.getenv(
    "BAYARGG_MERCHANT"
)
BAYARGG_WEBHOOK_SECRET = os.getenv(
    "BAYARGG_WEBHOOK_SECRET"
)
# -------------------------
# Cashi.id
# -------------------------
CASHI_API_KEY = os.getenv(
    "CASHI_API_KEY"
)
CASHI_BASE_URL = os.getenv(
    "CASHI_BASE_URL",
    "https://cashi.id"
)
# =========================
# MANUAL QR PAYMENT
# =========================
MANUAL_QR_FILE_ID = os.getenv(
    "MANUAL_QR_FILE_ID",
    "AgACAgUAAxkBAAIMYGp15ZcsP2J7BoXpsM5CXQLsjGkJAAJBGGsbEgexV1bJafVx9Y3uAQADAgADeQADPQQ"
)
MANUAL_PAYMENT_NAME = os.getenv(
    "MANUAL_PAYMENT_NAME",
    "QRIS Manual"
)
# =========================
# CHANNEL
# =========================
CHANNEL_ID = int(
    os.getenv(
        "CHANNEL_ID",
        "-1003978483597"
    )
)
GROUP_ID = int(
    os.getenv(
        "GROUP_ID",
        str(CHANNEL_ID)
    )
)
NOTIF_CHANNEL_ID = int(
    os.getenv(
        "NOTIF_CHANNEL_ID",
        "-1004413314849"
    )
)
# Public channel links used by the More Menu.
# Keep these configurable so the bot never needs
# hard-coded Telegram invite links in handler code.
REVIEW_CHANNEL_URL = os.getenv(
    "REVIEW_CHANNEL_URL",
    "https://t.me/inforobotnew"
)
NOTIFICATION_CHANNEL_URL = os.getenv(
    "NOTIFICATION_CHANNEL_URL",
    "https://t.me/+iG0rS6GFY3Y2NTNk"
)
TRANSACTION_CHANNEL_URL = os.getenv(
    "TRANSACTION_CHANNEL_URL",
    "https://t.me/+0ddS3Ha4c2pkNmJl"
)
ALL_CODE_CHANNEL_URL = os.getenv(
    "ALL_CODE_CHANNEL_URL",
    "https://t.me/inforobotnew"
)
# =========================
# WITHDRAW
# =========================
WITHDRAW_CHANNEL_ID = int(
    os.getenv(
        "WITHDRAW_CHANNEL_ID",
        "-1004413314849"
    )
)
# =========================
# ADMIN
# =========================
ADMIN_IDS = [
    int(x.strip())
    for x in os.getenv(
        "ADMIN_IDS",
        "6847035364"
    ).split(",")
    if x.strip().isdigit()
]
VVIP_USERS = {
    99887766,
    55667788,
}
# =========================
# VALIDATION
# =========================
if not BOT_TOKEN:
    raise ValueError(
        "BOT_TOKEN belum di-set di Railway Variables"
    )
if not DATABASE_URL:
    raise ValueError(
        "DATABASE_URL belum di-set"
    )
if not STORAGE_CHANNEL_ID:
    raise ValueError(
        "STORAGE_CHANNEL_ID belum di-set"
    )
if not BAYARGG_API_KEY:
    raise ValueError(
        "BAYARGG_API_KEY belum di-set di Railway Variables"
    )
if not CASHI_API_KEY:
    raise ValueError(
        "CASHI_API_KEY belum di-set di Railway Variables"
    )
if not WITHDRAW_CHANNEL_ID:
    raise ValueError(
        "WITHDRAW_CHANNEL_ID belum di-set"
    )
