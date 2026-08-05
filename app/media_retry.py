from __future__ import annotations

import asyncio
import logging
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


def install_media_retry(engine_module: Any) -> None:
    """Retry transient Telegram failures for every quest media action forever."""

    engine_class = engine_module.QuestEngine
    if getattr(engine_class, "_media_retry_installed", False):
        return

    original_send_media = engine_class._send_media

    async def _send_media(self, chat_id: int, action) -> None:
        failure_number = 0
        while True:
            try:
                await original_send_media(self, chat_id, action)
                if failure_number:
                    logger.info(
                        "Media delivery recovered for chat %s after %s failed attempt(s): %s",
                        chat_id,
                        failure_number,
                        action.type,
                    )
                return
            except TelegramRetryAfter as exc:
                failure_number += 1
                delay = max(float(exc.retry_after) + 1.0, 1.0)
                logger.warning(
                    "Telegram rate-limited media delivery to chat %s; retry %s in %.1fs: %s",
                    chat_id,
                    failure_number,
                    delay,
                    action.type,
                )
            except (TelegramNetworkError, TelegramServerError) as exc:
                failure_number += 1
                delay = _network_retry_delay(failure_number)
                logger.warning(
                    "Transient Telegram media failure for chat %s; retry %s in %.1fs: %s (%s)",
                    chat_id,
                    failure_number,
                    delay,
                    action.type,
                    exc,
                )

            await asyncio.sleep(delay)

    engine_class._send_media = _send_media
    engine_class._media_retry_installed = True
