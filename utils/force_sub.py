import logging

from aiogram import Bot
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
)

# =========================
# FORCE SUB CHANNELS
# =========================
CHANNELS = [
    -1003978483597,
    -1004413314849,
]


# =========================
# CHECK FORCE SUB
# =========================
async def check_force_sub(bot: Bot, user_id: int) -> bool:
    """
    Return:
        True  -> User sudah join semua channel.
        False -> User belum join / terjadi error.
    """

    for channel_id in CHANNELS:
        try:
            member = await bot.get_chat_member(
                chat_id=channel_id,
                user_id=user_id,
            )

            logging.info(
                "CHANNEL %s | USER %s | STATUS %s",
                channel_id,
                user_id,
                member.status,
            )

            if member.status not in (
                "member",
                "administrator",
                "creator",
            ):
                logging.warning(
                    "USER %s BELUM JOIN CHANNEL %s (STATUS=%s)",
                    user_id,
                    channel_id,
                    member.status,
                )
                return False

        except TelegramBadRequest as e:
            logging.exception(
                "ForceSub TelegramBadRequest | %s | %s",
                channel_id,
                e,
            )
            return False

        except TelegramForbiddenError as e:
            logging.exception(
                "ForceSub TelegramForbiddenError | %s | %s",
                channel_id,
                e,
            )
            return False

        except Exception as e:
            logging.exception(
                "ForceSub Unknown Error | %s | %s",
                channel_id,
                e,
            )
            return False

    logging.info("USER %s LULUS FORCE SUB", user_id)
    return True
