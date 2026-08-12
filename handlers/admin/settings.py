from aiogram import Router, F, Bot
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from datetime import datetime
import asyncio

from database import get_pool
from handlers.admin.admins import is_admin


router = Router()


# =========================
# DB SETTINGS
# =========================

async def get_setting(pool, key, default=None):
    value = await pool.fetchval(
        """
        SELECT value
        FROM settings
        WHERE key=$1
        """,
        key
    )

    return value if value is not None else default


async def set_setting(pool, key, value):
    await pool.execute(
        """
        INSERT INTO settings(key, value)
        VALUES($1, $2)

        ON CONFLICT(key)
        DO UPDATE
        SET value = EXCLUDED.value
        """,
        key,
        str(value)
    )


# =========================
# FSM
# =========================

class AdminState(StatesGroup):
    add_admin = State()
    add_owner = State()


class SchedulerState(StatesGroup):
    waiting_time = State()
    waiting_text = State()


class MaintenanceState(StatesGroup):
    waiting_text = State()


# =========================
# SETTINGS MENU
# =========================

@router.callback_query(F.data == "admin_settings")
async def admin_settings(call: CallbackQuery):

    if not is_admin(call.from_user.id):
        return await call.answer(
            "❌ Tidak memiliki akses",
            show_alert=True
        )

    pool = await get_pool()

    maintenance = await get_setting(
        pool,
        "maintenance",
        "off"
    )

    scheduler = await get_setting(
        pool,
        "scheduler",
        "off"
    )

    maintenance_icon = "🟢 ON" if maintenance == "on" else "🔴 OFF"
    scheduler_icon = "🟢 ON" if scheduler == "on" else "🔴 OFF"

    kb = InlineKeyboardMarkup(
        inline_keyboard=[

            [
                InlineKeyboardButton(
                    text="👑 Add Owner",
                    callback_data="add_owner"
                )
            ],

            [
                InlineKeyboardButton(
                    text="🛡 Add Admin",
                    callback_data="add_admin"
                )
            ],

            [
                InlineKeyboardButton(
                    text=f"🛠 Maintenance ({maintenance_icon})",
                    callback_data="set_maintenance"
                )
            ],

            [
                InlineKeyboardButton(
                    text=f"⏰ Scheduler ({scheduler_icon})",
                    callback_data="set_scheduler"
                )
            ],

            [
                InlineKeyboardButton(
                    text="⬅ Admin Menu",
                    callback_data="admin_home"
                )
            ]

        ]
    )

    await call.message.edit_text(
        (
            "⚙️ <b>ADMIN SETTINGS</b>\n"
            "━━━━━━━━━━━━━━\n\n"
            "Kelola seluruh pengaturan bot dari menu di bawah."
        ),
        parse_mode="HTML",
        reply_markup=kb
    )

    await call.answer()



# =========================
# ADD ADMIN
# =========================

@router.callback_query(F.data == "add_admin")
async def add_admin(
    call: CallbackQuery,
    state: FSMContext
):

    if not is_admin(call.from_user.id):
        return await call.answer(
            "❌ Tidak memiliki akses",
            show_alert=True
        )

    await state.clear()
    await state.set_state(AdminState.add_admin)

    await call.message.answer(
        (
            "🛡 <b>TAMBAH ADMIN</b>\n\n"
            "Kirim Telegram ID user."
        ),
        parse_mode="HTML"
    )

    await call.answer()


@router.message(AdminState.add_admin)
async def save_admin(
    message: Message,
    state: FSMContext
):

    if not message.text or not message.text.isdigit():
        return await message.answer(
            "❌ Telegram ID harus berupa angka."
        )

    user_id = int(message.text)

    pool = await get_pool()

    user = await pool.fetchrow(
        """
        SELECT chat_id
        FROM users
        WHERE chat_id=$1
        """,
        user_id
    )

    if not user:
        await state.clear()
        return await message.answer(
            "❌ User tidak ditemukan."
        )

    await pool.execute(
        """
        INSERT INTO admins(user_id, role)
        VALUES($1,'admin')

        ON CONFLICT(user_id)
        DO UPDATE
        SET role='admin'
        """,
        user_id
    )

    await pool.execute(
        """
        UPDATE users
        SET is_admin=TRUE
        WHERE chat_id=$1
        """,
        user_id
    )

    await message.answer(
        (
            "✅ <b>Admin berhasil ditambahkan.</b>\n\n"
            f"🆔 <code>{user_id}</code>"
        ),
        parse_mode="HTML"
    )

    await state.clear()


# =========================
# ADD OWNER
# =========================

@router.callback_query(F.data == "add_owner")
async def add_owner(
    call: CallbackQuery,
    state: FSMContext
):

    if not is_admin(call.from_user.id):
        return await call.answer(
            "❌ Tidak memiliki akses",
            show_alert=True
        )

    await state.clear()
    await state.set_state(AdminState.add_owner)

    await call.message.answer(
        (
            "👑 <b>TAMBAH OWNER</b>\n\n"
            "Kirim Telegram ID user."
        ),
        parse_mode="HTML"
    )

    await call.answer()


@router.message(AdminState.add_owner)
async def save_owner(
    message: Message,
    state: FSMContext
):

    if not message.text or not message.text.isdigit():
        return await message.answer(
            "❌ Telegram ID harus berupa angka."
        )

    user_id = int(message.text)

    pool = await get_pool()

    user = await pool.fetchrow(
        """
        SELECT chat_id
        FROM users
        WHERE chat_id=$1
        """,
        user_id
    )

    if not user:
        await state.clear()
        return await message.answer(
            "❌ User tidak ditemukan."
        )

    await pool.execute(
        """
        INSERT INTO admins(user_id, role)
        VALUES($1,'owner')

        ON CONFLICT(user_id)
        DO UPDATE
        SET role='owner'
        """,
        user_id
    )

    await pool.execute(
        """
        UPDATE users
        SET is_admin=TRUE
        WHERE chat_id=$1
        """,
        user_id
    )

    await message.answer(
        (
            "👑 <b>Owner berhasil ditambahkan.</b>\n\n"
            f"🆔 <code>{user_id}</code>"
        ),
        parse_mode="HTML"
    )

    await state.clear()



# =========================
# MAINTENANCE
# =========================

@router.callback_query(F.data == "set_maintenance")
async def maintenance_menu(call: CallbackQuery):

    if not is_admin(call.from_user.id):
        return await call.answer(
            "❌ Tidak memiliki akses",
            show_alert=True
        )

    pool = await get_pool()

    status = await get_setting(
        pool,
        "maintenance",
        "off"
    )

    text_status = "🟢 ON" if status == "on" else "🔴 OFF"

    kb = InlineKeyboardMarkup(
        inline_keyboard=[

            [
                InlineKeyboardButton(
                    text=f"{text_status}",
                    callback_data="toggle_maintenance"
                )
            ],

            [
                InlineKeyboardButton(
                    text="✏️ Ubah Pesan",
                    callback_data="set_maint_text"
                )
            ],

            [
                InlineKeyboardButton(
                    text="⬅ Kembali",
                    callback_data="admin_settings"
                )
            ]

        ]
    )

    await call.message.edit_text(
        (
            "🛠 <b>MAINTENANCE MODE</b>\n"
            "━━━━━━━━━━━━━━\n\n"
            f"Status : <b>{text_status}</b>"
        ),
        parse_mode="HTML",
        reply_markup=kb
    )

    await call.answer()


# =========================
# TOGGLE MAINTENANCE
# =========================

@router.callback_query(F.data == "toggle_maintenance")
async def toggle_maintenance(call: CallbackQuery):

    if not is_admin(call.from_user.id):
        return

    pool = await get_pool()

    old = await get_setting(
        pool,
        "maintenance",
        "off"
    )

    new = "off" if old == "on" else "on"

    await set_setting(
        pool,
        "maintenance",
        new
    )

    await call.answer(
        f"Maintenance {new.upper()}",
        show_alert=True
    )

    await maintenance_menu(call)


# =========================
# SET MAINTENANCE MESSAGE
# =========================

@router.callback_query(F.data == "set_maint_text")
async def maint_text(
    call: CallbackQuery,
    state: FSMContext
):

    if not is_admin(call.from_user.id):
        return

    await state.clear()
    await state.set_state(
        MaintenanceState.waiting_text
    )

    await call.message.answer(
        (
            "✏️ <b>UBAH PESAN MAINTENANCE</b>\n\n"
            "Silakan kirim pesan baru."
        ),
        parse_mode="HTML"
    )

    await call.answer()


@router.message(MaintenanceState.waiting_text)
async def save_maint(
    message: Message,
    state: FSMContext
):

    text = (message.text or "").strip()

    if not text:
        return await message.answer(
            "❌ Pesan tidak boleh kosong."
        )

    pool = await get_pool()

    await set_setting(
        pool,
        "maintenance_text",
        text
    )

    await message.answer(
        "✅ Pesan maintenance berhasil disimpan."
    )

    await state.clear()



# =========================
# SCHEDULER
# =========================

@router.callback_query(F.data == "set_scheduler")
async def scheduler_menu(call: CallbackQuery):

    if not is_admin(call.from_user.id):
        return await call.answer(
            "❌ Tidak memiliki akses",
            show_alert=True
        )

    pool = await get_pool()

    status = await get_setting(
        pool,
        "scheduler",
        "off"
    )

    jam = await get_setting(
        pool,
        "schedule_time",
        "09:00"
    )

    status_text = "🟢 ON" if status == "on" else "🔴 OFF"

    kb = InlineKeyboardMarkup(
        inline_keyboard=[

            [
                InlineKeyboardButton(
                    text=status_text,
                    callback_data="toggle_scheduler"
                )
            ],

            [
                InlineKeyboardButton(
                    text="🕒 Set Jam",
                    callback_data="set_time"
                )
            ],

            [
                InlineKeyboardButton(
                    text="📝 Set Pesan",
                    callback_data="set_text"
                )
            ],

            [
                InlineKeyboardButton(
                    text="⬅ Kembali",
                    callback_data="admin_settings"
                )
            ]

        ]
    )

    await call.message.edit_text(
        (
            "⏰ <b>SCHEDULER</b>\n"
            "━━━━━━━━━━━━━━\n\n"
            f"Status : <b>{status_text}</b>\n"
            f"Jam : <code>{jam}</code>"
        ),
        parse_mode="HTML",
        reply_markup=kb
    )

    await call.answer()


# =========================
# TOGGLE SCHEDULER
# =========================

@router.callback_query(F.data == "toggle_scheduler")
async def toggle_scheduler(call: CallbackQuery):

    if not is_admin(call.from_user.id):
        return

    pool = await get_pool()

    old = await get_setting(
        pool,
        "scheduler",
        "off"
    )

    new = "off" if old == "on" else "on"

    await set_setting(
        pool,
        "scheduler",
        new
    )

    await call.answer(
        f"Scheduler {new.upper()}",
        show_alert=True
    )

    await scheduler_menu(call)


# =========================
# SET TIME
# =========================

@router.callback_query(F.data == "set_time")
async def set_time(
    call: CallbackQuery,
    state: FSMContext
):

    await state.clear()
    await state.set_state(
        SchedulerState.waiting_time
    )

    await call.message.answer(
        (
            "🕒 Kirim jam scheduler.\n\n"
            "Format:\n"
            "<code>09:00</code>"
        ),
        parse_mode="HTML"
    )

    await call.answer()


@router.message(SchedulerState.waiting_time)
async def save_time(
    message: Message,
    state: FSMContext
):

    value = (message.text or "").strip()

    try:
        datetime.strptime(value, "%H:%M")
    except ValueError:
        return await message.answer(
            "❌ Format salah.\nGunakan HH:MM"
        )

    pool = await get_pool()

    await set_setting(
        pool,
        "schedule_time",
        value
    )

    await message.answer(
        f"✅ Jam scheduler disimpan : <code>{value}</code>",
        parse_mode="HTML"
    )

    await state.clear()


# =========================
# SET TEXT
# =========================

@router.callback_query(F.data == "set_text")
async def set_text(
    call: CallbackQuery,
    state: FSMContext
):

    await state.clear()

    await state.set_state(
        SchedulerState.waiting_text
    )

    await call.message.answer(
        "📝 Kirim pesan scheduler."
    )

    await call.answer()


@router.message(SchedulerState.waiting_text)
async def save_text(
    message: Message,
    state: FSMContext
):

    text = (message.text or "").strip()

    if not text:
        return await message.answer(
            "❌ Pesan tidak boleh kosong."
        )

    pool = await get_pool()

    await set_setting(
        pool,
        "schedule_text",
        text
    )

    await message.answer(
        "✅ Pesan scheduler berhasil disimpan."
    )

    await state.clear()


# =========================
# WORKER
# =========================

async def scheduler_loop(bot: Bot):

    last = None

    while True:

        try:

            pool = await get_pool()

            enabled = await get_setting(
                pool,
                "scheduler",
                "off"
            )

            jam = await get_setting(
                pool,
                "schedule_time",
                "09:00"
            )

            text = await get_setting(
                pool,
                "schedule_text",
                "Halo!"
            )

            now = datetime.now().astimezone().strftime("%H:%M")

            if enabled == "on" and now == jam and last != now:

                users = await pool.fetch(
                    """
                    SELECT chat_id
                    FROM users
                    """
                )

                for user in users:

                    try:

                        await bot.send_message(
                            chat_id=user["chat_id"],
                            text=text
                        )

                        await asyncio.sleep(0.05)

                    except Exception:
                        pass

                last = now

            await asyncio.sleep(10)

        except Exception as e:

            print("Scheduler Error:", e)

            await asyncio.sleep(10)
