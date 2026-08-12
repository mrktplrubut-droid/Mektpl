import asyncio
import json
import logging
import re
import time
import uuid

from typing import Dict
from contextlib import asynccontextmanager

from aiogram import Router, F
from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)

from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import CHANNEL_ID, STORAGE_CHANNEL_ID, BOT_USERNAME
from database import get_pool
from keyboards.join import join_kb
from utils.force_sub import check_force_sub


router = Router()

MAX_MEDIA = 200
UPDATE_DELAY = 0.5
COPY_DELAY = 0.2

logging.basicConfig(level=logging.INFO)

_last_update: Dict[int,float] = {}
_user_locks: Dict[int,asyncio.Lock] = {}

_copy_lock = asyncio.Lock()


def get_lock(user_id:int):
    if user_id not in _user_locks:
        _user_locks[user_id] = asyncio.Lock()
    return _user_locks[user_id]


@asynccontextmanager
async def user_lock(user_id:int):
    async with get_lock(user_id):
        yield


async def copy_to_storage(bot,from_chat_id:int,message_id:int):

    async with _copy_lock:

        while True:
            try:
                msg = await bot.copy_message(
                    chat_id=STORAGE_CHANNEL_ID,
                    from_chat_id=from_chat_id,
                    message_id=message_id
                )

                await asyncio.sleep(COPY_DELAY)
                return msg

            except TelegramRetryAfter as e:
                await asyncio.sleep(e.retry_after + 1)

            except Exception:
                logging.exception("COPY STORAGE ERROR")
                await asyncio.sleep(2)
                raise


async def safe_update(bot,chat_id:int,message_id:int,text:str,reply_markup=None):

    now=time.time()

    if chat_id in _last_update:
        if now-_last_update[chat_id] < UPDATE_DELAY:
            return

    _last_update[chat_id]=now

    try:
        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=text,
            parse_mode="HTML",
            reply_markup=reply_markup
        )

    except TelegramBadRequest:
        pass

    except Exception:
        logging.exception("UPDATE ERROR")


BAD_WORDS={
    "bocil",
    "child",
    "underage",
    "minor"
}


def normalize(text:str):
    return re.sub(
        r"[^a-z0-9]",
        "",
        text.lower()
    )


def is_bad(text:str):
    clean=normalize(text)
    return any(x in clean for x in BAD_WORDS)


class UploadState(StatesGroup):
    upload=State()
    wait_title=State()
    wait_price=State()


# ==========================================
# START UPLOAD BUTTON
# ==========================================

@router.callback_query(F.data == "upfile")
async def start_upload(call: CallbackQuery, state: FSMContext):

    await call.answer()

    if not await check_force_sub(call.bot, call.from_user.id):
        return await call.message.answer(
            "❌ Kamu belum join channel.",
            reply_markup=join_kb()
        )

    await state.clear()
    await state.set_state(UploadState.upload)

    text = (
        "📦 <b>UPLOAD MODE</b>\n\n"
        "Silakan kirim file.\n"
        f"Maksimal {MAX_MEDIA} media.\n\n"
        "Jika selesai tekan STOP & SAVE."
    )

    try:
        await call.message.edit_text(
            text,
            parse_mode="HTML"
        )

        progress_id = call.message.message_id

    except Exception:

        msg = await call.message.answer(
            text,
            parse_mode="HTML"
        )

        progress_id = msg.message_id

    await state.update_data(
        upload_mode=True,
        media=[],
        title=None,
        share_media=True,
        is_paid=False,
        price=0,
        payment_provider=None,
        saving=False,
        progress_msg_id=progress_id
    )


import random

async def generate_code():
    pool = await get_pool()
    chars = "0123456789aiueo"

    while True:
        code = "".join(random.choices(chars, k=40))

        check = await pool.fetchval(
            "SELECT 1 FROM files WHERE code=$1",
            code
        )

        if not check:
            return code

# ==========================================
# RECEIVE MEDIA
# ==========================================

@router.message(F.document | F.video | F.photo)
async def receive_media(message: Message, state: FSMContext):

    user_id = message.from_user.id

    async with user_lock(user_id):

        data = await state.get_data()

        # Upload hanya jika user sudah menekan tombol Upload
        if not data.get("upload_mode"):
            return

        media = data.get("media", [])

        if len(media) >= MAX_MEDIA:
            return await message.answer(
                f"❌ Maksimal {MAX_MEDIA} media."
            )

        try:
            copied = await copy_to_storage(
                message.bot,
                message.chat.id,
                message.message_id
            )
            storage_id = copied.message_id

        except Exception:
            return await message.answer(
                "⚠️ Gagal menyimpan ke storage."
            )

        if message.document:
            file_type = "document"
            file_id = message.document.file_id
            file_name = message.document.file_name
            file_size = message.document.file_size or 0

        elif message.video:
            file_type = "video"
            file_id = message.video.file_id
            file_name = getattr(message.video, "file_name", None)
            file_size = message.video.file_size or 0

        else:
            file_type = "photo"
            file_id = message.photo[-1].file_id
            file_name = None
            file_size = message.photo[-1].file_size or 0

        if any(x["file_id"] == file_id for x in media):
            try:
                await message.delete()
            except Exception:
                pass

            return await message.answer(
                "⚠️ File tersebut sudah ditambahkan."
            )

        media.append({
            "message_id": storage_id,
            "file_id": file_id,
            "type": file_type,
            "file_name": file_name,
            "file_size": file_size,
            "position": len(media) + 1
        })

        await state.update_data(media=media)

        kb = InlineKeyboardBuilder()

        kb.button(
            text="⏹ STOP & SAVE",
            callback_data="save_upfile"
        )

        kb.button(
            text="❌ BATAL",
            callback_data="cancel_upfile"
        )

        kb.adjust(1)

        progress_id = data.get("progress_msg_id")

        if progress_id:
            await safe_update(
                message.bot,
                message.chat.id,
                progress_id,
                (
                    "📦 <b>UPLOAD MODE</b>\n\n"
                    f"📁 Media : <b>{len(media)}/{MAX_MEDIA}</b>\n\n"
                    "Kirim lagi atau tekan STOP & SAVE."
                ),
                kb.as_markup()
            )

        try:
            await message.delete()
        except Exception:
            pass


@router.callback_query(F.data=="cancel_upfile")
async def cancel_upload(call:CallbackQuery,state:FSMContext):

    await call.answer()

    async with user_lock(call.from_user.id):

        data=await state.get_data()

        progress_id=data.get("progress_msg_id")

        if progress_id:
            try:
                await call.bot.delete_message(
                    call.message.chat.id,
                    progress_id
                )
            except:
                pass

        await state.clear()

        try:
            await call.message.edit_text(
                "❌ <b>Upload dibatalkan.</b>",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            InlineKeyboardButton(
                                text="🏠 Home",
                                callback_data="home"
                            )
                        ]
                    ]
                )
            )
        except:
            await call.message.answer(
                "❌ <b>Upload dibatalkan.</b>",
                parse_mode="HTML"
            )


@router.callback_query(F.data=="save_upfile")
async def choose_share_mode(call:CallbackQuery,state:FSMContext):

    await call.answer()

    async with user_lock(call.from_user.id):

        data=await state.get_data()
        media=data.get("media",[])

        if not media:
            return await call.answer(
                "❌ Belum ada media.",
                show_alert=True
            )

        kb=InlineKeyboardBuilder()

        kb.button(
            text="🔗 Share Media",
            callback_data="share_yes"
        )

        kb.button(
            text="🔒 Private",
            callback_data="share_no"
        )

        kb.adjust(2)

        await call.message.edit_text(
            "📦 <b>PILIH MODE FILE</b>\n\n"
            "🔗 Share Media\n"
            "File bisa dibuka melalui link.\n\n"
            "🔒 Private\n"
            "File hanya lewat code.",
            parse_mode="HTML",
            reply_markup=kb.as_markup()
        )


@router.callback_query(F.data.startswith("share_"))
async def share_handler(call:CallbackQuery,state:FSMContext):

    await call.answer()

    async with user_lock(call.from_user.id):

        share=call.data=="share_yes"

        await state.update_data(
            share_media=share
        )

        await state.set_state(
            UploadState.wait_title
        )

        await call.message.edit_text(
            "📝 <b>MASUKKAN JUDUL FILE</b>\n\n"
            "Kirim judul file.\n"
            "Ketik /skip untuk otomatis.",
            parse_mode="HTML"
        )


@router.message(UploadState.wait_title)
async def input_title(message:Message,state:FSMContext):

    async with user_lock(message.from_user.id):

        title=(message.text or "").strip()

        if title.lower()=="/skip":
            title="Untitled"

        else:
            if len(title)<3:
                return await message.answer(
                    "❌ Judul minimal 3 karakter."
                )

            if is_bad(title):
                return await message.answer(
                    "❌ Judul tidak diperbolehkan."
                )


        await state.update_data(
            title=title
        )

        kb=InlineKeyboardBuilder()

        kb.button(
            text="🆓 FREE",
            callback_data="file_free"
        )

        kb.button(
            text="💰 PAID",
            callback_data="file_paid"
        )

        kb.adjust(2)

        await message.answer(
            "💎 <b>PILIH TIPE FILE</b>\n\n"
            "🆓 FREE = Gratis\n"
            "💰 PAID = Berbayar",
            parse_mode="HTML",
            reply_markup=kb.as_markup()
        )


@router.callback_query(F.data == "file_free")
async def file_free(call: CallbackQuery, state: FSMContext):

    await call.answer()

    async with user_lock(call.from_user.id):

        await state.update_data(
            is_paid=False,
            price=0,
            payment_provider=None,
            saving_msg_id=call.message.message_id
        )

        try:
            await call.message.edit_text(
                "⏳ <b>Menyimpan file...</b>",
                parse_mode="HTML"
            )
        except:
            pass

        await finalize_save(
            call.message,
            state,
            call.from_user.id
        )


@router.callback_query(F.data=="file_paid")
async def file_paid(call:CallbackQuery,state:FSMContext):

    await call.answer()

    await state.set_state(
        UploadState.wait_price
    )

    await call.message.edit_text(
        "💰 <b>MASUKKAN HARGA FILE</b>\n\n"
        "Minimal Rp1.000.",
        parse_mode="HTML"
    )

@router.message(UploadState.wait_price)
async def input_price(message: Message, state: FSMContext):

    async with user_lock(message.from_user.id):

        text = (message.text or "").replace(".", "").replace(",", "").strip()

        if not text.isdigit():
            return await message.answer(
                "❌ Harga harus berupa angka."
            )

        price = int(text)

        if price < 1000:
            return await message.answer(
                "❌ Harga minimal Rp1.000."
            )

        await state.update_data(
            is_paid=True,
            price=price,
            payment_provider="bayargg"
        )

        saving_msg = await message.answer(
            (
                "⏳ <b>Menyimpan file...</b>\n\n"
                f"💰 Harga : Rp{price:,}"
            ).replace(",", "."),
            parse_mode="HTML"
        )

        await state.update_data(
            saving_msg_id=saving_msg.message_id
        )

        await finalize_save(
            message,
            state,
            message.from_user.id
        )


async def finalize_save(message: Message, state: FSMContext, user_id: int):

    data = await state.get_data()

    if data.get("saving"):
        return

    await state.update_data(saving=True)

    try:
        media = [
            x for x in data.get("media", [])
            if x.get("message_id") and x.get("file_id")
        ]

        if not media:
            await state.update_data(saving=False)
            return await message.answer("❌ Tidak ada media.")

        title = data.get("title") or "Untitled"
        creator = message.from_user.full_name or "Unknown"

        share_media = data.get("share_media", True)
        is_paid = data.get("is_paid", False)
        price = data.get("price", 0)
        payment_provider = data.get("payment_provider")

        code = await generate_code()

        media_json = json.dumps(media, ensure_ascii=False)
        media_count = len(media)

        values = []

        for item in media:
            values.append((
                code,
                int(item["message_id"]),
                item["file_id"],
                item["type"],
                item.get("file_size", 0),
                title,
                item.get("position", 0)
            ))

        pool = await get_pool()

        async with pool.acquire() as conn:
            async with conn.transaction():

                await conn.execute(
                    """
                    INSERT INTO public.users(
                        user_id,
                        chat_id,
                        username,
                        full_name
                    )
                    VALUES($1,$2,$3,$4)
                    ON CONFLICT(user_id)
                    DO UPDATE SET
                        chat_id = EXCLUDED.chat_id,
                        username = EXCLUDED.username,
                        full_name = EXCLUDED.full_name
                    """,
                    user_id,
                    user_id,
                    message.from_user.username,
                    message.from_user.full_name
                )

                await conn.execute(
                    """
                    INSERT INTO files(
                        code,title,creator,media,
                        share_media,is_share,
                        owner_id,seller_id,
                        media_count,expires_at,
                        is_paid,price,
                        payment_provider,
                        view_count,
                        download_count,
                        favorite_count
                    )
                    VALUES(
                        $1,$2,$3,$4,
                        $5,$6,
                        $7,$8,
                        $9,NULL,
                        $10,$11,
                        $12,
                        0,0,0
                    )
                    """,
                    code,
                    title,
                    creator,
                    media_json,
                    share_media,
                    share_media,
                    user_id,
                    user_id,
                    media_count,
                    is_paid,
                    price,
                    payment_provider
                )

                if values:
                    await conn.executemany(
                        """
                        INSERT INTO medias(
                            code,
                            message_id,
                            file_id,
                            file_type,
                            file_size,
                            title,
                            position
                        )
                        VALUES($1,$2,$3,$4,$5,$6,$7)
                        """,
                        values
                    )

        progress_id = data.get("progress_msg_id")

        if progress_id:
            try:
                await message.bot.delete_message(
                    message.chat.id,
                    progress_id
                )
            except Exception:
                pass

        saving_msg_id = data.get("saving_msg_id")

        if saving_msg_id:
            try:
                await message.bot.delete_message(
                    message.chat.id,
                    saving_msg_id
                )
            except Exception:
                pass

        await state.clear()

        video_count = sum(1 for x in media if x["type"] == "video")
        photo_count = sum(1 for x in media if x["type"] == "photo")
        document_count = sum(1 for x in media if x["type"] == "document")

        info = []

        if video_count:
            info.append(f"{video_count} Video")
        if photo_count:
            info.append(f"{photo_count} Photo")
        if document_count:
            info.append(f"{document_count} Document")

        files_info = " • ".join(info) if info else "0 File"

        mode = (
            f"💰 PAID Rp{price:,}".replace(",", ".")
            if is_paid
            else "🆓 FREE"
        )

        await message.answer(
            (
                "✅ <b>FILE BERHASIL DISIMPAN</b>\n\n"
                f"📝 <b>Judul</b> : {title}\n"
                f"📦 <b>Total Media</b> : {media_count}\n"
                f"🔑 <b>Code</b> : <code>{code}</code>\n"
                f"💎 <b>Status</b> : {mode}"
            ),
            parse_mode="HTML"
        )

        try:
            bot_name = (await message.bot.get_me()).username or "Unknown"

            safe_id = str(user_id)
            if len(safe_id) > 4:
                safe_id = safe_id[:2] + "****" + safe_id[-2:]

            await message.bot.send_message(
                chat_id=CHANNEL_ID,
                text=(
                    "📤 <b>UPLOAD BARU</b>\n\n"
                    f"🤖 Bot : @{bot_name}\n"
                    f"🆔 ID : <code>{safe_id}</code>\n"
                    f"📝 Judul : {title}\n"
                    f"📦 Total : {media_count} Media\n"
                    f"💎 Status : {mode}\n"
                    f"🔑 Code : <code>{code}</code>"
                ),
                parse_mode="HTML"
            )

        except Exception:
            logging.exception("LOG CHANNEL ERROR")

    except Exception:
        logging.exception("FINAL SAVE ERROR")

        await state.update_data(saving=False)

        await message.answer(
            "❌ Terjadi kesalahan saat menyimpan file.\nSilakan coba lagi."
        )
