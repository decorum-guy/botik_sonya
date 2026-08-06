from __future__ import annotations

from typing import Any

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode

from app.config import Settings
from app.health import install_admin_ping
from app.media_retry import TELEGRAM_REQUEST_TIMEOUT_SECONDS
from app.memory_batch_preview import install_memory_batch_preview
from app.memory_capture_middleware import install_memory_capture
from app.memory_debug_commands import install_memory_debug
from app.memory_modes import install_memory_mode_commands
from app.storage import Storage


def _install_runtime_handlers(
    bot_app: Any,
    storage: Storage | None = None,
) -> None:
    """Register handlers without assuming app.main has finished initialization.

    Roadmap Studio calls ``build_bot`` before it assigns its local Storage instance
    to ``app.main``. Diagnostic commands can be registered immediately, while the
    Studio-level UserTrackingMiddleware already performs early memory capture.
    The normal bot passes/exports storage before polling and therefore installs the
    router-level capture middleware as well.
    """

    install_admin_ping(bot_app.router)
    install_memory_debug(bot_app.router)
    install_memory_batch_preview(bot_app.router)
    install_memory_mode_commands(bot_app.router)

    capture_storage = storage or getattr(bot_app, "storage", None)
    if capture_storage is not None:
        install_memory_capture(bot_app.router, capture_storage)


def build_bot(settings: Settings, *, storage: Storage | None = None) -> Bot:
    """Create one Bot instance with optional proxy support from .env."""
    session = AiohttpSession(
        proxy=settings.proxy_url,
        timeout=TELEGRAM_REQUEST_TIMEOUT_SECONDS,
    )
    bot = Bot(
        token=settings.bot_token,
        session=session,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )

    # app.main has finished defining its router by the time build_bot is called,
    # but Roadmap Studio may not have assigned app.main.storage yet.
    import app.main as bot_app

    _install_runtime_handlers(bot_app, storage)
    return bot
