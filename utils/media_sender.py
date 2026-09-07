"""Safe Telegram media delivery helpers."""
import asyncio
import logging

from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramRetryAfter,
)

from config import STORAGE_CHANNEL_ID
from database import get_pool

logger = logging.getLogger(__name__)

# Keep concurrent CopyMessage calls low. RetryAfter remains the authority.
# One outbound storage copy at a time. TelegramRetryAfter remains authoritative.
_COPY_SEMAPHORE = asyncio.Semaphore(1)
_COPY_DELAY = 1.0
_BLOCKED_CHATS: set[int] = set()



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

    try:
        chat_key = int(chat_id)
    except (TypeError, ValueError):
        return None

    # A known-invalid destination must not generate hundreds of identical
    # Telegram requests/log lines during a batch.
    if chat_key in _BLOCKED_CHATS:
        logger.info("COPY SKIPPED INVALID CHAT | chat=%s | message=%s", chat_id, message_id)
        return None

    async with _COPY_SEMAPHORE:
        while True:
            try:
                result = await bot.copy_message(
                    chat_id=chat_id,
                    from_chat_id=STORAGE_CHANNEL_ID,
                    message_id=message_id,
                    protect_content=protect_content,
                )
                effective_delay = delay
                if delay == _COPY_DELAY:
                    try:
                        pool = await get_pool()
                        setting = await pool.fetchval(
                            "SELECT value FROM settings WHERE key=$1",
                            "telegram_storage_delay",
                        )
                        effective_delay = max(0.0, float(setting)) if setting is not None else delay
                    except Exception:
                        effective_delay = delay
                if effective_delay > 0:
                    await asyncio.sleep(effective_delay)
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

            except TelegramForbiddenError as exc:
                # Bot was blocked or lacks access. Do not hammer this chat again.
                _BLOCKED_CHATS.add(chat_key)
                logger.warning(
                    "COPY DESTINATION BLOCKED | chat=%s | message=%s | error=%s",
                    chat_id, message_id, exc,
                )
                return None

            except TelegramBadRequest as exc:
                error = str(exc).lower()
                permanent = (
                    "chat not found" in error
                    or "user is deactivated" in error
                    or "bot was blocked" in error
                    or "message to copy not found" in error
                    or "message not found" in error
                )
                if permanent and ("chat not found" in error or "user is deactivated" in error or "bot was blocked" in error):
                    _BLOCKED_CHATS.add(chat_key)
                logger.warning(
                    "COPY PERMANENT ERROR | chat=%s | message=%s | permanent=%s | error=%s",
                    chat_id, message_id, permanent, exc,
                )
                return None

            except Exception as exc:
                logger.exception(
                    "COPY ERROR | chat=%s | message=%s | error=%s",
                    chat_id, message_id, exc,
                )
                return None
