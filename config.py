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
# Cashi.id
# ------------------------------------------------------------

# API Key dari:
# CASHI Dashboard -> Settings -> API Keys

CASHI_API_KEY = os.getenv(
    "CASHI_API_KEY",
    "",
).strip()


# Secret Key untuk verifikasi webhook.
# JANGAN pernah ditaruh di frontend atau dikirim ke user.

CASHI_SECRET_KEY = os.getenv(
    "CASHI_SECRET_KEY",
    "",
).strip()


# Base URL CASHI

CASHI_BASE_URL = os.getenv(
    "CASHI_BASE_URL",
    "https://cashi.id",
).strip().rstrip("/")


# Endpoint Create Order
CASHI_CREATE_ORDER_URL = (
    f"{CASHI_BASE_URL}/api/create-order"
)


# Endpoint Check Status
CASHI_CHECK_STATUS_URL = (
    f"{CASHI_BASE_URL}/api/check-status"
)


# Kode channel pembayaran.
#
# Contoh dari dokumentasi:
# QRIS_CUSTOM
#
# Bisa diganti sesuai kode channel yang tersedia
# di Dashboard CASHI.

CASHI_PAYMENT_CHANNEL = os.getenv(
    "CASHI_PAYMENT_CHANNEL",
    "QRIS_CUSTOM",
).strip()


# Minimum dan maksimum pembayaran CASHI
CASHI_MIN_AMOUNT = 2000
CASHI_MAX_AMOUNT = 10_000_000


# ------------------------------------------------------------
# Cashi Payment Settings
# ------------------------------------------------------------

# CASHI belum dijadikan payment utama sampai
# handler + webhook selesai dipasang.

CASHI_ENABLED = (
    bool(CASHI_API_KEY)
    and bool(CASHI_SECRET_KEY)
)


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

    Tidak membuat bot crash hanya karena
    environment variable kosong atau salah.
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
# PAYMENT MODE
# ============================================================

# ============================================================
# PENTING
# ============================================================
#
# Jangan aktifkan CASHI sebagai payment utama sebelum:
#
# 1. create-order selesai
# 2. QR/checkout CASHI selesai
# 3. webhook selesai
# 4. signature HMAC selesai
# 5. status SETTLED selesai
# 6. database file_purchases selesai di-update
#
# Untuk sementara:
#
# MANUAL = AKTIF
# CASHI  = SIAP DIKONFIGURASIKAN
# AUTO   = BELUM AKTIF
#
# ============================================================

PAYMENT_MODE = os.getenv(
    "PAYMENT_MODE",
    "manual",
).strip().lower()


MANUAL_PAYMENT_ENABLED = True


AUTO_PAYMENT_ENABLED = (
    PAYMENT_MODE == "cashi"
    and CASHI_ENABLED
)


# ============================================================
# VALIDATION
# ============================================================

# ------------------------------------------------------------
# BOT
# ------------------------------------------------------------

if not BOT_TOKEN:
    raise ValueError(
        "BOT_TOKEN belum di-set di Railway Variables"
    )


# ------------------------------------------------------------
# DATABASE
# ------------------------------------------------------------

if not DATABASE_URL:
    raise ValueError(
        "DATABASE_URL belum di-set di Railway Variables"
    )


# ------------------------------------------------------------
# STORAGE CHANNEL
# ------------------------------------------------------------

if not STORAGE_CHANNEL_ID:
    raise ValueError(
        "STORAGE_CHANNEL_ID belum di-set di Railway Variables"
    )


# ------------------------------------------------------------
# ADMIN
# ------------------------------------------------------------

if not ADMIN_IDS:
    raise ValueError(
        "ADMIN_IDS belum di-set di Railway Variables"
    )


# ------------------------------------------------------------
# MANUAL QR
# ------------------------------------------------------------

if MANUAL_PAYMENT_ENABLED and not MANUAL_QR_FILE_ID:
    raise ValueError(
        "MANUAL_QR_FILE_ID belum di-set"
    )


# ------------------------------------------------------------
# WITHDRAW CHANNEL
# ------------------------------------------------------------

if not WITHDRAW_CHANNEL_ID:
    raise ValueError(
        "WITHDRAW_CHANNEL_ID belum di-set"
    )


# ------------------------------------------------------------
# CASHI
# ------------------------------------------------------------

if PAYMENT_MODE == "cashi":

    if not CASHI_API_KEY:
        raise ValueError(
            "CASHI_API_KEY belum di-set di Railway Variables"
        )

    if not CASHI_SECRET_KEY:
        raise ValueError(
            "CASHI_SECRET_KEY belum di-set di Railway Variables"
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
