from aiogram.fsm.state import State, StatesGroup


# =========================
# GET FILE (input code)
# =========================
class GetFileState(StatesGroup):
    wait_code = State()


# =========================
# UPLOAD FILE SYSTEM
# =========================
class UploadState(StatesGroup):
    wait_type = State()
    wait_price = State()


# =========================
# BUY / PAYMENT FLOW
# =========================
class BuyState(StatesGroup):
    wait_payment = State()
    wait_confirm = State()


# =========================
# OPTIONAL: ADMIN / CONTROL (kalau nanti dipakai)
# =========================
class AdminState(StatesGroup):
    wait_broadcast = State()
    wait_user_action = State()


# =========================
# PAYMENT CHECK STATE (BayarGG webhook flow optional)
# =========================
class PaymentState(StatesGroup):
    wait_invoice = State()
    wait_callback = State()

# =========================
# 💸 WITHDRAW
# =========================
class WithdrawState(StatesGroup):
    amount = State()
    account_name = State()
    account_number = State()
    bank_name = State()
    confirm = State()
