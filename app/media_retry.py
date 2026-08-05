from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram.exceptions import (
    TelegramNetworkError,
    TelegramRetryAfter,
    TelegramServerError,
)

logger = logging.getLogger(__name__)

# Large uploads over a proxy can legitimately take longer than aiogram's
# default 60-second HTTP timeout. This is used as the default session timeout;
# /ping supplies its own short timeout so a dead proxy is reported quickly.
TELEGRAM_REQUEST_TIMEOUT_SECONDS = 300.0

# The quest must not stop because of a temporary proxy, network or Telegram
# outage. After the quick retries, keep trying once per minute until delivery
# succeeds or the process is deliberately stopped.
NETWORK_RETRY_DELAYS_SECONDS = (2.0, 5.0, 10.0, 20.0, 30.0, 60.0)


def _network_retry_delay(failure_number: int) -> float:
    index = min(max(failure_number - 1, 0), len(NETWORK_RETRY_DELAYS_SECONDS) - 1)
    return NETWORK_RETRY_DELAYS_SECONDS[index]


async def retry_transient_telegram[ResultT](
    operation: Callable[[], Awaitable[ResultT]],
    *,
    chat_id: int,
    label: str,
) -> ResultT:
    """Retry temporary Telegram/proxy failures until the operation succeeds.

    Permanent Bot API errors are intentionally not caught here. They must reach
    the caller so it can choose a content-specific fallback instead of looping
    forever on a missing file, forbidden chat or malformed request.
    """

    failure_number = 0
    while True:
        try:
            result = await operation()
            if failure_number:
                logger.info(
                    "Telegram delivery recovered for chat %s after %s failed attempt(s): %s",
                    chat_id,
                    failure_number,
                    label,
                )
            return result
        except TelegramRetryAfter as exc:
            failure_number += 1
            delay = max(float(exc.retry_after) + 1.0, 1.0)
            logger.warning(
                "Telegram rate-limited delivery to chat %s; retry %s in %.1fs: %s",
                chat_id,
                failure_number,
                delay,
                label,
            )
        except (TelegramNetworkError, TelegramServerError) as exc:
            failure_number += 1
            delay = _network_retry_delay(failure_number)
            logger.warning(
                "Transient Telegram failure for chat %s; retry %s in %.1fs: %s (%s)",
                chat_id,
                failure_number,
                delay,
                label,
                exc,
            )

        await asyncio.sleep(delay)


def install_media_retry(engine_module: Any) -> None:
    """Retry transient Telegram failures for every quest media action forever."""

    engine_class = engine_module.QuestEngine
    if getattr(engine_class, "_media_retry_installed", False):
        return

    original_send_media = engine_class._send_media

    async def _send_media(self, chat_id: int, action) -> None:
        await retry_transient_telegram(
            lambda: original_send_media(self, chat_id, action),
            chat_id=chat_id,
            label=action.type,
        )

    engine_class._send_media = _send_media
    engine_class._media_retry_installed = True
