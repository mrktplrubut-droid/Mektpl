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

BAYARGG_API_KEY = os.getenv("BAYARGG_API_KEY")
BAYARGG_MERCHANT = os.getenv("BAYARGG_MERCHANT")
BAYARGG_WEBHOOK_SECRET = os.getenv(
    "BAYARGG_WEBHOOK_SECRET"
)


# ------------------------------------------------------------
# Cashi.id - OPTIONAL / LEGACY
# ------------------------------------------------------------

CASHI_API_KEY = os.getenv("CASHI_API_KEY")

CASHI_BASE_URL = os.getenv(
    "CASHI_BASE_URL",
    "https://cashi.id",
).rstrip("/")


# ============================================================
# MANUAL QR PAYMENT
# ============================================================

MANUAL_QR_FILE_ID = os.getenv(
    "MANUAL_QR_FILE_ID",
    "AgACAgUAAxkBAAIMYGp15ZcsP2J7BoXpsM5CXQLsjGkJAAJBGGsbEgexV1bJafVx9Y3uAQADAgADeQADPQQ",
).strip()

MANUAL_PAYMENT_NAME = os.getenv(
    "MANUAL_PAYMENT_NAME",
    "QRIS Manual",
).strip()


# ============================================================
# CHANNEL
# ============================================================

def env_int(name: str, default: int = 0) -> int:
    """
    Safe integer environment variable parser.
    Tidak membuat bot crash hanya karena env kosong/salah.
    """
    raw = os.getenv(name)

    if raw is None or not str(raw).strip():
        return default

    try:
        return int(str(raw).strip())
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
    """
    Support:
        ADMIN_IDS=123456789
        ADMIN_IDS=123456789,987654321
        ADMIN_IDS=123456789;987654321
    """

    if value is None:
        return []

    result = []

    for item in str(value).replace(";", ",").split(","):
        item = item.strip()

        if not item:
            continue

        try:
            user_id = int(item)

            if user_id not in result:
                result.append(user_id)

        except (ValueError, TypeError):
            continue

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

# BOT
if not BOT_TOKEN:
    raise ValueError(
        "BOT_TOKEN belum di-set di Railway Variables"
    )


# DATABASE
if not DATABASE_URL:
    raise ValueError(
        "DATABASE_URL belum di-set di Railway Variables"
    )


# STORAGE CHANNEL
if not STORAGE_CHANNEL_ID:
    raise ValueError(
        "STORAGE_CHANNEL_ID belum di-set di Railway Variables"
    )


# ADMIN
if not ADMIN_IDS:
    raise ValueError(
        "ADMIN_IDS belum di-set di Railway Variables"
    )


# MANUAL QR
if not MANUAL_QR_FILE_ID:
    raise ValueError(
        "MANUAL_QR_FILE_ID belum di-set"
    )


# WITHDRAW CHANNEL
if not WITHDRAW_CHANNEL_ID:
    raise ValueError(
        "WITHDRAW_CHANNEL_ID belum di-set"
    )


# ============================================================
# PAYMENT MODE
# ============================================================

# Payment otomatis lama sengaja TIDAK diwajibkan.
# Semua pembelian saat ini menggunakan QR manual.

PAYMENT_MODE = "manual"

MANUAL_PAYMENT_ENABLED = True

AUTO_PAYMENT_ENABLED = False


# ============================================================
# STARTUP INFO
# ============================================================

print(
    "=================================================="
)

print("Mektpl configuration loaded")

print(
    f"BOT_USERNAME      : @{BOT_USERNAME}"
)

print(
    f"PAYMENT_MODE      : {PAYMENT_MODE}"
)

print(
    f"MANUAL_PAYMENT    : {'ON' if MANUAL_PAYMENT_ENABLED else 'OFF'}"
)

print(
    f"AUTO_PAYMENT      : {'ON' if AUTO_PAYMENT_ENABLED else 'OFF'}"
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
