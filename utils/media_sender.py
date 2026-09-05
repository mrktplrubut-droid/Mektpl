"""Safe Telegram media delivery helpers."""
import asyncio
import logging

from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramRetryAfter,
)

from config import STORAGE_CHANNEL_ID

logger = logging.getLogger(__name__)

# Keep concurrent CopyMessage calls low. RetryAfter remains the authority.
_COPY_SEMAPHORE = asyncio.Semaphore(2)
_COPY_DELAY = 0.20


async def safe_copy_from_storage(
    bot,
    chat_id,
    message_id,
    *,
    protect_content=False,
    max_retries=6,
    delay=_COPY_DELAY,
):
    """Copy one stored Telegram message with flood-control protection.

    Returns the copied Message on success, or None for permanent failures.
    RetryAfter is handled by waiting the exact server-provided duration.
    """
    try:
        message_id = int(message_id)
    except (TypeError, ValueError):
        return None

    retries = 0

    async with _COPY_SEMAPHORE:
        while True:
            try:
                result = await bot.copy_message(
                    chat_id=chat_id,
                    from_chat_id=STORAGE_CHANNEL_ID,
                    message_id=message_id,
                    protect_content=protect_content,
                )
                if delay > 0:
                    await asyncio.sleep(delay)
                return result

            except TelegramRetryAfter as exc:
                retries += 1
                if retries > max_retries:
                    logger.error(
                        "COPY RETRY LIMIT | chat=%s | message=%s | retries=%s",
                        chat_id, message_id, retries,
                    )
                    return None

                wait_for = max(float(exc.retry_after), 1.0) + 0.5
                logger.warning(
                    "TELEGRAM FLOOD CONTROL | chat=%s | message=%s | wait=%.1fs | retry=%s/%s",
                    chat_id, message_id, wait_for, retries, max_retries,
                )
                await asyncio.sleep(wait_for)

            except (TelegramForbiddenError, TelegramBadRequest) as exc:
                logger.warning(
                    "COPY PERMANENT ERROR | chat=%s | message=%s | error=%s",
                    chat_id, message_id, exc,
                )
                return None

            except Exception as exc:
                logger.exception(
                    "COPY ERROR | chat=%s | message=%s | error=%s",
                    chat_id, message_id, exc,
                )
                return None
