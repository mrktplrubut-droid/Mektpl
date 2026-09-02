import os
from dotenv import load_dotenv
load_dotenv()
# ============================================================
# GENERAL
# ============================================================
TIMEZONE = "Asia/Jakarta"
# ============================================================
# BOT
# ============================================================
BOT_TOKEN = os.getenv("BOT_TOKEN")
BOT_USERNAME = (
    os.getenv("BOT_USERNAME", "mktplbot")
    .lstrip("@")
    .strip()
)
BOT_URL = f"https://t.me/{BOT_USERNAME}"
# ============================================================
# DATABASE
# ============================================================
DATABASE_URL = os.getenv("DATABASE_URL")
try:
    STORAGE_CHANNEL_ID = int(
        os.getenv("STORAGE_CHANNEL_ID", "0").strip()
    )
except (ValueError, TypeError):
    STORAGE_CHANNEL_ID = 0
# ============================================================
# PAYMENT
# ============================================================
# ------------------------------------------------------------
# BayarGG - LEGACY / OPTIONAL
# ------------------------------------------------------------
BAYARGG_API_KEY = os.getenv(
    "BAYARGG_API_KEY",
    "",
).strip()
BAYARGG_MERCHANT = os.getenv(
    "BAYARGG_MERCHANT",
    "",
).strip()
BAYARGG_WEBHOOK_SECRET = os.getenv(
    "BAYARGG_WEBHOOK_SECRET",
    "",
).strip()
# ------------------------------------------------------------
# CASHI.ID
# ------------------------------------------------------------
CASHI_API_KEY = os.getenv(
    "CASHI_API_KEY",
    "",
).strip()
CASHI_SECRET_KEY = os.getenv(
    "CASHI_SECRET_KEY",
    "",
).strip()
CASHI_BASE_URL = os.getenv(
    "CASHI_BASE_URL",
    "https://cashi.id",
).strip().rstrip("/")
# Endpoint CASHI
CASHI_CREATE_ORDER_URL = (
    f"{CASHI_BASE_URL}/api/create-order"
)
CASHI_CHECK_STATUS_URL = (
    f"{CASHI_BASE_URL}/api/check-status"
)
# ------------------------------------------------------------
# CASHI PAYMENT CHANNEL
# ------------------------------------------------------------
CASHI_PAYMENT_CHANNEL = os.getenv(
    "CASHI_PAYMENT_CHANNEL",
    "QRIS_CUSTOM",
).strip()
# ------------------------------------------------------------
# CASHI LIMIT
# ------------------------------------------------------------
CASHI_MIN_AMOUNT = int(
    os.getenv(
        "CASHI_MIN_AMOUNT",
        "2000",
    )
)
CASHI_MAX_AMOUNT = int(
    os.getenv(
        "CASHI_MAX_AMOUNT",
        "10000000",
    )
)
# ============================================================
# PAYMENT MODE
# ============================================================
# IMPORTANT:
#
# cashi = CASHI menjadi payment utama
# manual = QR manual menjadi payment utama
#
# Default dibuat CASHI agar tombol Bayar tidak lagi
# diam karena handler payment diarahkan ke QR manual.
PAYMENT_MODE = os.getenv(
    "PAYMENT_MODE",
    "cashi",
).strip().lower()
# ============================================================
# CASHI STATUS
# ============================================================
CASHI_ENABLED = bool(
    CASHI_API_KEY
)
AUTO_PAYMENT_ENABLED = (
    PAYMENT_MODE == "cashi"
    and CASHI_ENABLED
)
# ============================================================
# MANUAL PAYMENT
# ============================================================
MANUAL_PAYMENT_ENABLED = (
    PAYMENT_MODE == "manual"
)
MANUAL_QR_FILE_ID = os.getenv(
    "MANUAL_QR_FILE_ID",
    "",
).strip()
MANUAL_PAYMENT_NAME = os.getenv(
    "MANUAL_PAYMENT_NAME",
    "QRIS Manual",
).strip()
# ============================================================
# CHANNEL
# ============================================================
def env_int(
    name: str,
    default: int = 0,
) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    raw = str(raw).strip()
    if not raw:
        return default
    try:
        return int(raw)
    except (ValueError, TypeError):
        return default
CHANNEL_ID = env_int(
    "CHANNEL_ID",
    -1003978483597,
)
GROUP_ID = env_int(
    "GROUP_ID",
    CHANNEL_ID,
)
NOTIF_CHANNEL_ID = env_int(
    "NOTIF_CHANNEL_ID",
    -1004413314849,
)
# ============================================================
# PUBLIC CHANNEL LINKS
# ============================================================
REVIEW_CHANNEL_URL = os.getenv(
    "REVIEW_CHANNEL_URL",
    "https://t.me/inforobotnew",
).strip()
NOTIFICATION_CHANNEL_URL = os.getenv(
    "NOTIFICATION_CHANNEL_URL",
    "https://t.me/+iG0rS6GFY3Y2NTNk",
).strip()
TRANSACTION_CHANNEL_URL = os.getenv(
    "TRANSACTION_CHANNEL_URL",
    "https://t.me/+0ddS3Ha4c2pkNmJl",
).strip()
ALL_CODE_CHANNEL_URL = os.getenv(
    "ALL_CODE_CHANNEL_URL",
    "https://t.me/inforobotnew",
).strip()
# ============================================================
# WITHDRAW
# ============================================================
WITHDRAW_CHANNEL_ID = env_int(
    "WITHDRAW_CHANNEL_ID",
    -1004413314849,
)
# ============================================================
# ADMIN
# ============================================================
def parse_admin_ids(value) -> list[int]:
    if value is None:
        return []
    result = []
    for item in str(value).replace(
        ";",
        ",",
    ).split(","):
        item = item.strip()
        if not item:
            continue
        try:
            user_id = int(item)
        except (ValueError, TypeError):
            continue
        if user_id not in result:
            result.append(user_id)
    return result
ADMIN_IDS = parse_admin_ids(
    os.getenv(
        "ADMIN_IDS",
        "6847035364",
    )
)
# ============================================================
# VVIP
# ============================================================
VVIP_USERS = {
    99887766,
    55667788,
}
# ============================================================
# VALIDATION
# ============================================================
if not BOT_TOKEN:
    raise ValueError(
        "BOT_TOKEN belum di-set di Railway Variables"
    )
if not DATABASE_URL:
    raise ValueError(
        "DATABASE_URL belum di-set di Railway Variables"
    )
if not STORAGE_CHANNEL_ID:
    raise ValueError(
        "STORAGE_CHANNEL_ID belum di-set di Railway Variables"
    )
if not ADMIN_IDS:
    raise ValueError(
        "ADMIN_IDS belum di-set di Railway Variables"
    )
if not WITHDRAW_CHANNEL_ID:
    raise ValueError(
        "WITHDRAW_CHANNEL_ID belum di-set di Railway Variables"
    )
# ============================================================
# CASHI VALIDATION
# ============================================================
if PAYMENT_MODE == "cashi":
    if not CASHI_API_KEY:
        raise ValueError(
            "CASHI_API_KEY belum di-set di Railway Variables"
        )
    if not CASHI_BASE_URL:
        raise ValueError(
            "CASHI_BASE_URL belum di-set"
        )
# ============================================================
# MANUAL VALIDATION
# ============================================================
if PAYMENT_MODE == "manual":
    if not MANUAL_QR_FILE_ID:
        raise ValueError(
            "MANUAL_QR_FILE_ID belum di-set"
        )
# ============================================================
# STARTUP INFO
# ============================================================
print(
    "=================================================="
)
print(
    "Mektpl configuration loaded"
)
print(
    f"BOT_USERNAME      : @{BOT_USERNAME}"
)
print(
    f"PAYMENT_MODE      : {PAYMENT_MODE}"
)
print(
    f"MANUAL_PAYMENT    : "
    f"{'ON' if MANUAL_PAYMENT_ENABLED else 'OFF'}"
)
print(
    f"CASHI_ENABLED     : "
    f"{'ON' if CASHI_ENABLED else 'OFF'}"
)
print(
    f"AUTO_PAYMENT      : "
    f"{'ON' if AUTO_PAYMENT_ENABLED else 'OFF'}"
)
print(
    f"CASHI_CHANNEL     : {CASHI_PAYMENT_CHANNEL}"
)
print(
    f"CASHI_MIN         : Rp {CASHI_MIN_AMOUNT:,}"
    .replace(",", ".")
)
print(
    f"CASHI_MAX         : Rp {CASHI_MAX_AMOUNT:,}"
    .replace(",", ".")
)
print(
    f"ADMIN_COUNT       : {len(ADMIN_IDS)}"
)
print(
    f"STORAGE_CHANNEL   : {STORAGE_CHANNEL_ID}"
)
print(
    f"NOTIF_CHANNEL     : {NOTIF_CHANNEL_ID}"
)
print(
    "=================================================="
)
