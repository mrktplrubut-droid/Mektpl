from aiogram import Router, F
from aiogram.types import (
    CallbackQuery,
    Message,
)
from aiogram.fsm.state import (
    StatesGroup,
    State,
)
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder

from database import get_pool
from .dashboard import is_admin, rupiah

router = Router()

PAGE_SIZE = 10


# =========================
# STATE
# =========================

class FilesState(StatesGroup):
    waiting_code = State()
    waiting_price = State()
# =========================
# MENU FILE
# =========================

@router.callback_query(F.data == "admin_files")
async def admin_files(
    call: CallbackQuery,
    state: FSMContext
):

    if not is_admin(call.from_user.id):
        return await call.answer(
            "No Access",
            show_alert=True
        )

    await state.clear()

    pool = await get_pool()

    total = await pool.fetchval(
        """
        SELECT COUNT(*)
        FROM files
        """
    ) or 0

    paid = await pool.fetchval(
        """
        SELECT COUNT(*)
        FROM files
        WHERE is_paid=TRUE
        """
    ) or 0

    free = await pool.fetchval(
        """
        SELECT COUNT(*)
        FROM files
        WHERE is_paid=FALSE
        """
    ) or 0

    # =========================
    # BUTTON FILE MENU
    # =========================

    kb = InlineKeyboardBuilder()

    kb.button(
        text="📋 List File",
        callback_data="files_list:1"
    )

    kb.button(
        text="🔍 Cari Code",
        callback_data="files_search"
    )

    kb.button(
        text="⬅ Admin Menu",
        callback_data="admin_home"
    )

    kb.adjust(1)

    await call.message.edit_text(
        (
            "📂 <b>FILES PANEL</b>\n"
            "━━━━━━━━━━━━━━\n\n"

            f"📁 Total File : <b>{total}</b>\n"
            f"🆓 Free : <b>{free}</b>\n"
            f"💰 Paid : <b>{paid}</b>"
        ),
        parse_mode="HTML",
        reply_markup=kb.as_markup()
    )

    await call.answer()


# =========================
# LIST FILE
# =========================

@router.callback_query(F.data.startswith("files_list:"))
async def files_list(
    call: CallbackQuery
):

    if not is_admin(call.from_user.id):
        return

    page = int(call.data.split(":")[1])

    if page < 1:
        page = 1

    offset = (page - 1) * PAGE_SIZE

    pool = await get_pool()

    total = await pool.fetchval(
        """
        SELECT COUNT(*)
        FROM files
        """
    ) or 0

    rows = await pool.fetch(
        """
        SELECT
            code,
            title,
            price,
            is_paid,
            download_count,
            media_count
        FROM files
        ORDER BY created_at DESC
        LIMIT $1
        OFFSET $2
        """,
        PAGE_SIZE,
        offset
    )

    pages = max((total + PAGE_SIZE - 1) // PAGE_SIZE, 1)

    text = (
        "📂 <b>DAFTAR FILE</b>\n"
        "━━━━━━━━━━━━━━\n\n"
    )

    if not rows:

        text += "Tidak ada file."

    else:

        for i, file in enumerate(
            rows,
            start=offset + 1
        ):

            status = (
                "💰"
                if file["is_paid"]
                else
                "🆓"
            )

            harga = (
                rupiah(file["price"])
                if file["is_paid"]
                else "FREE"
            )

            text += (
                f"{i}. <code>{file['code']}</code>\n"
                f"📄 {file['title'] or '-'}\n"
                f"{status} {harga}\n"
                f"🖼 {file['media_count']} media\n"
                f"📥 {file['download_count']} download\n\n"
            )

    kb = InlineKeyboardBuilder()

    if page > 1:
        kb.button(
            text="⬅",
            callback_data=f"files_list:{page-1}"
        )

    kb.button(
        text=f"{page}/{pages}",
        callback_data="ignore"
    )

    if page < pages:
        kb.button(
            text="➡",
            callback_data=f"files_list:{page+1}"
        )

    kb.button(
        text="🏠 Files Menu",
        callback_data="admin_files"
    )

    kb.adjust(3, 1)

    await call.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=kb.as_markup()
    )

    await call.answer()

# =========================
# SEARCH FILE
# =========================

@router.callback_query(F.data == "files_search")
async def files_search(
    call: CallbackQuery,
    state: FSMContext
):

    if not is_admin(call.from_user.id):
        return

    await state.clear()
    await state.set_state(FilesState.waiting_code)

    kb = InlineKeyboardBuilder()

    kb.button(
        text="⬅ Kembali",
        callback_data="admin_files"
    )

    await call.message.edit_text(
        (
            "🔍 <b>CARI FILE</b>\n\n"
            "Silakan kirim CODE File."
        ),
        parse_mode="HTML",
        reply_markup=kb.as_markup()
    )

    await call.answer()


# =========================
# PROCESS SEARCH
# =========================

@router.message(FilesState.waiting_code)
async def process_search_file(
    message: Message,
    state: FSMContext
):

    if not is_admin(message.from_user.id):
        return

    code = (message.text or "").strip()

    if not code:
        return await message.answer("❌ Code tidak boleh kosong.")

    pool = await get_pool()

    file = await pool.fetchrow(
        """
        SELECT *
        FROM files
        WHERE LOWER(code)=LOWER($1)
        """,
        code
    )

    if not file:
        await state.clear()
        return await message.answer(
            "❌ File tidak ditemukan."
        )

    status = (
        "💰 Berbayar"
        if file["is_paid"]
        else "🆓 Gratis"
    )

    harga = (
        rupiah(file["price"])
        if file["is_paid"]
        else "FREE"
    )

    text = (
        "📄 <b>DETAIL FILE</b>\n"
        "━━━━━━━━━━━━━━\n\n"

        f"🔑 CODE : <code>{file['code']}</code>\n"
        f"📄 Judul : {file['title'] or '-'}\n"
        f"👤 Creator : {file['creator'] or '-'}\n\n"

        f"🆔 Owner : <code>{file['owner_id']}</code>\n"
        f"🛒 Seller : <code>{file['seller_id']}</code>\n\n"

        f"💳 Status : {status}\n"
        f"💰 Harga : {harga}\n\n"

        f"🖼 Media : {file['media_count']}\n"
        f"👁 View : {file['view_count']}\n"
        f"📥 Download : {file['download_count']}\n"
        f"❤️ Favorite : {file['favorite_count']}\n"
        f"🛍 Buy : {file['buy_count']}\n\n"

        f"📂 Category : {file['category'] or '-'}\n"
        f"📅 Upload : {file['created_at']}"
    )

    kb = InlineKeyboardBuilder()

    kb.button(
        text="💰 Edit Harga",
        callback_data=f"file_price:{file['id']}"
    )

    kb.button(
        text="🔄 Gratis/Bayar",
        callback_data=f"file_toggle:{file['id']}"
    )

    kb.button(
        text="🗑 Hapus File",
        callback_data=f"file_delete:{file['id']}"
    )

    kb.button(
        text="⬅ Files Menu",
        callback_data="admin_files"
    )

    kb.adjust(2, 1, 1)

    await message.answer(
        text,
        parse_mode="HTML",
        reply_markup=kb.as_markup()
    )

    await state.clear()

# =========================
# EDIT HARGA
# =========================

@router.callback_query(F.data.startswith("file_price:"))
async def file_price(
    call: CallbackQuery,
    state: FSMContext
):

    if not is_admin(call.from_user.id):
        return

    file_id = int(call.data.split(":")[1])

    await state.update_data(file_id=file_id)
    await state.set_state(FilesState.waiting_price)

    await call.message.answer(
        "💰 Kirim harga baru (angka).\n\nContoh:\n5000"
    )

    await call.answer()


@router.message(FilesState.waiting_price)
async def process_price(
    message: Message,
    state: FSMContext
):

    if not is_admin(message.from_user.id):
        return

    if not message.text or not message.text.isdigit():
        return await message.answer(
            "❌ Harga harus berupa angka."
        )

    price = int(message.text)

    data = await state.get_data()
    file_id = data["file_id"]

    pool = await get_pool()

    await pool.execute(
        """
        UPDATE files
        SET
            price=$1,
            is_paid=TRUE
        WHERE id=$2
        """,
        price,
        file_id
    )

    await message.answer(
        f"✅ Harga berhasil diubah menjadi {rupiah(price)}"
    )

    await state.clear()


# =========================
# GRATIS / BERBAYAR
# =========================

@router.callback_query(F.data.startswith("file_toggle:"))
async def file_toggle(
    call: CallbackQuery
):

    if not is_admin(call.from_user.id):
        return

    file_id = int(call.data.split(":")[1])

    pool = await get_pool()

    file = await pool.fetchrow(
        """
        SELECT
            is_paid
        FROM files
        WHERE id=$1
        """,
        file_id
    )

    if not file:
        return await call.answer(
            "File tidak ditemukan",
            show_alert=True
        )

    new_status = not file["is_paid"]

    if new_status:

        await pool.execute(
            """
            UPDATE files
            SET is_paid=TRUE
            WHERE id=$1
            """,
            file_id
        )

        msg = "💰 File menjadi BERBAYAR"

    else:

        await pool.execute(
            """
            UPDATE files
            SET
                is_paid=FALSE,
                price=0
            WHERE id=$1
            """,
            file_id
        )

        msg = "🆓 File menjadi GRATIS"

    await call.answer(msg, show_alert=True)


# =========================
# KONFIRMASI HAPUS CODE
# =========================

@router.callback_query(F.data.startswith("file_delete:"))
async def delete_file_confirm(
    call: CallbackQuery
):

    if not is_admin(call.from_user.id):
        return

    file_id = int(call.data.split(":")[1])

    pool = await get_pool()

    file = await pool.fetchrow(
        """
        SELECT
            id,
            code,
            title
        FROM files
        WHERE id=$1
        """,
        file_id
    )

    if not file:
        return await call.answer(
            "File tidak ditemukan.",
            show_alert=True
        )

    kb = InlineKeyboardBuilder()

    kb.button(
        text="✅ Ya, Hapus",
        callback_data=f"file_delete_yes:{file_id}"
    )

    kb.button(
        text="❌ Batal",
        callback_data=f"file_delete_cancel:{file_id}"
    )

    kb.adjust(2)

    await call.message.edit_text(
        (
            "⚠️ <b>KONFIRMASI HAPUS CODE</b>\n"
            "━━━━━━━━━━━━━━\n\n"

            f"🔑 Code : <code>{file['code']}</code>\n"
            f"📄 Judul : {file['title'] or '-'}\n\n"

            "⚠️ File akan dihapus dari database.\n"
            "Tindakan ini tidak dapat dibatalkan.\n\n"

            "Apakah kamu yakin ingin menghapusnya?"
        ),
        parse_mode="HTML",
        reply_markup=kb.as_markup()
    )

    await call.answer()


# =========================
# EKSEKUSI HAPUS
# =========================

@router.callback_query(
    F.data.startswith("file_delete_yes:")
)
async def delete_file_execute(
    call: CallbackQuery
):

    if not is_admin(call.from_user.id):
        return

    file_id = int(call.data.split(":")[1])

    pool = await get_pool()

    file = await pool.fetchrow(
        """
        SELECT code
        FROM files
        WHERE id=$1
        """,
        file_id
    )

    if not file:
        return await call.answer(
            "File sudah tidak ditemukan.",
            show_alert=True
        )

    result = await pool.execute(
        """
        DELETE FROM files
        WHERE id=$1
        """,
        file_id
    )

    await call.message.edit_text(
        (
            "🗑 <b>CODE BERHASIL DIHAPUS</b>\n"
            "━━━━━━━━━━━━━━\n\n"
            f"🔑 Code : <code>{file['code']}</code>\n\n"
            "File telah dihapus dari database."
        ),
        parse_mode="HTML"
    )

    await call.answer(
        "Code berhasil dihapus."
    )


# =========================
# BATAL HAPUS
# =========================

@router.callback_query(
    F.data.startswith("file_delete_cancel:")
)
async def delete_file_cancel(
    call: CallbackQuery
):

    if not is_admin(call.from_user.id):
        return

    file_id = int(call.data.split(":")[1])

    pool = await get_pool()

    file = await pool.fetchrow(
        """
        SELECT *
        FROM files
        WHERE id=$1
        """,
        file_id
    )

    if not file:
        return await call.answer(
            "File tidak ditemukan.",
            show_alert=True
        )

    status = (
        "💰 Berbayar"
        if file["is_paid"]
        else "🆓 Gratis"
    )

    harga = (
        rupiah(file["price"])
        if file["is_paid"]
        else "FREE"
    )

    text = (
        "📄 <b>DETAIL FILE</b>\n"
        "━━━━━━━━━━━━━━\n\n"

        f"🔑 CODE : <code>{file['code']}</code>\n"
        f"📄 Judul : {file['title'] or '-'}\n"
        f"👤 Creator : {file['creator'] or '-'}\n\n"

        f"🆔 Owner : <code>{file['owner_id']}</code>\n"
        f"🛒 Seller : <code>{file['seller_id']}</code>\n\n"

        f"💳 Status : {status}\n"
        f"💰 Harga : {harga}\n\n"

        f"🖼 Media : {file['media_count']}\n"
        f"👁 View : {file['view_count']}\n"
        f"📥 Download : {file['download_count']}\n"
        f"❤️ Favorite : {file['favorite_count']}\n"
        f"🛍 Buy : {file['buy_count']}\n\n"

        f"📂 Category : {file['category'] or '-'}\n"
        f"📅 Upload : {file['created_at']}"
    )

    kb = InlineKeyboardBuilder()

    kb.button(
        text="💰 Edit Harga",
        callback_data=f"file_price:{file['id']}"
    )

    kb.button(
        text="🔄 Gratis/Bayar",
        callback_data=f"file_toggle:{file['id']}"
    )

    kb.button(
        text="🗑 Hapus Code",
        callback_data=f"file_delete:{file['id']}"
    )

    kb.button(
        text="⬅ Files Menu",
        callback_data="admin_files"
    )

    kb.adjust(2, 1, 1)

    await call.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=kb.as_markup()
    )

    await call.answer()
