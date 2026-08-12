from aiogram import Router, F
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.exceptions import (
    TelegramForbiddenError,
    TelegramRetryAfter,
    TelegramBadRequest
)

import asyncio

from database import get_pool
from config import ADMIN_IDS


router = Router()


BATCH_SIZE = 20
BASE_DELAY = 0.2



def is_admin(uid):
    return uid in ADMIN_IDS



# =========================
# FSM
# =========================

class BroadcastState(StatesGroup):

    waiting_message = State()
    choose_target = State()
    confirm = State()



# =========================
# START
# =========================

@router.callback_query(F.data=="admin_broadcast")
async def start(call:CallbackQuery,state:FSMContext):

    if not is_admin(call.from_user.id):
        return await call.answer(
            "❌ No access",
            show_alert=True
        )


    await state.set_state(
        BroadcastState.waiting_message
    )


    await call.message.edit_text(
        "📢 <b>BROADCAST CENTER</b>\n\n"
        "Kirim pesan broadcast.\n\n"
        "Support:\n"
        "✅ Text\n"
        "✅ Foto\n"
        "✅ Video\n"
        "✅ Document\n"
        "✅ Forward\n\n"
        "/cancel untuk batal",
        parse_mode="HTML"
    )



# =========================
# SAVE MESSAGE
# =========================

@router.message(
    BroadcastState.waiting_message
)
async def save_message(
    message:Message,
    state:FSMContext
):

    await state.update_data(
        msg=message
    )


    kb=InlineKeyboardMarkup(
        inline_keyboard=[

            [
                InlineKeyboardButton(
                    text="👤 User",
                    callback_data="bc_user"
                )
            ],

            [
                InlineKeyboardButton(
                    text="📢 Channel / Group",
                    callback_data="bc_chat"
                )
            ],

            [
                InlineKeyboardButton(
                    text="🌍 Semua",
                    callback_data="bc_all"
                )
            ]

        ]
    )


    await message.answer(
        "🎯 Pilih target:",
        reply_markup=kb
    )


    await state.set_state(
        BroadcastState.choose_target
    )



# =========================
# GET TARGET
# =========================


async def get_targets(
    pool,
    target
):

    result=[]


    # USER TELEGRAM
    if target in ("user","all"):

        rows=await pool.fetch(
            """
            SELECT chat_id
            FROM users
            WHERE chat_id IS NOT NULL
            """
        )


        for r in rows:

            result.append(
                {
                    "chat_id":r["chat_id"],
                    "type":"user"
                }
            )



    # CHANNEL / GROUP
    if target in ("chat", "all"):
        pass



    # remove duplicate

    seen=set()
    clean=[]

    for x in result:

        if x["chat_id"] not in seen:

            clean.append(x)
            seen.add(x["chat_id"])


    return clean




# =========================
# TARGET BUTTON
# =========================


@router.callback_query(
    F.data.startswith("bc_")
)
async def target_select(
    call:CallbackQuery,
    state:FSMContext
):

    target=call.data.replace(
        "bc_",
        ""
    )


    if target=="all":
        target="all"

    elif target=="user":
        target="user"

    elif target=="chat":
        target="chat"

    else:
        return


    await state.update_data(
        target=target
    )


    data=await state.get_data()

    msg=data["msg"]



    kb=InlineKeyboardMarkup(
        inline_keyboard=[

            [
                InlineKeyboardButton(
                    text="🚀 Kirim",
                    callback_data="broadcast_send"
                )
            ],

            [
                InlineKeyboardButton(
                    text="❌ Cancel",
                    callback_data="bc_cancel"
                )
            ]

        ]
    )



    await call.message.answer(
        "👀 Preview:"
    )


    await msg.copy_to(
        call.message.chat.id,
        reply_markup=kb
    )


    await state.set_state(
        BroadcastState.confirm
    )



# =========================
# SEND ENGINE
# =========================


async def send_engine(
    msg,
    targets,
    pool,
    progress
):


    total=len(targets)

    success=0
    failed=0
    blocked=0


    lock=asyncio.Lock()



    async def worker(item):

        nonlocal success,failed,blocked


        cid=item["chat_id"]


        for retry in range(3):

            try:


                await msg.copy_to(
                    cid
                )


                async with lock:
                    success+=1


                return



            except TelegramForbiddenError:


                async with lock:
                    blocked+=1


                return



            except TelegramRetryAfter as e:


                await asyncio.sleep(
                    e.retry_after
                )



            except Exception as e:

                print(
                    "SEND ERROR",
                    cid,
                    e
                )

                await asyncio.sleep(1)



        async with lock:
            failed+=1




    for i in range(
        0,
        total,
        BATCH_SIZE
    ):


        batch=targets[
            i:i+BATCH_SIZE
        ]


        await asyncio.gather(
            *[
                worker(x)
                for x in batch
            ]
        )


        try:

            await progress.edit_text(
                "🚀 <b>Broadcast Running</b>\n\n"
                f"👥 Total : {total}\n"
                f"✅ Sent : {success}\n"
                f"🚫 Block : {blocked}\n"
                f"❌ Failed : {failed}\n\n"
                f"{min(i+BATCH_SIZE,total)}/{total}",
                parse_mode="HTML"
            )

        except:
            pass



        await asyncio.sleep(
            BASE_DELAY
        )



    return (
        total,
        success,
        failed,
        blocked
    )



# =========================
# SEND
# =========================


@router.callback_query(
    F.data=="broadcast_send"
)
async def send_now(
    call:CallbackQuery,
    state:FSMContext
):


    data=await state.get_data()


    pool=await get_pool()


    targets=await get_targets(
        pool,
        data["target"]
    )


    if not targets:

        return await call.message.edit_text(
            "❌ Target kosong"
        )



    progress=await call.message.edit_text(
        "🚀 Starting..."
    )



    result=await send_engine(
        data["msg"],
        targets,
        pool,
        progress
    )


    await state.clear()


    await progress.edit_text(
        "✅ <b>BROADCAST SELESAI</b>\n\n"
        f"👥 Total : {result[0]}\n"
        f"✅ Sent : {result[1]}\n"
        f"🚫 Block : {result[3]}\n"
        f"❌ Failed : {result[2]}",
        parse_mode="HTML"
    )



# =========================
# CANCEL
# =========================


@router.callback_query(
    F.data=="bc_cancel"
)
async def cancel(
    call:CallbackQuery,
    state:FSMContext
):

    await state.clear()

    await call.message.edit_text(
        "❌ Broadcast dibatalkan"
    )
