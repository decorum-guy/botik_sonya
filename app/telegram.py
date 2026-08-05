from __future__ import annotations

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode

from app.config import Settings
from app.health import install_admin_ping
from app.media_debug_commands import install_memory_debug
from app.media_retry import TELEGRAM_REQUEST_TIMEOUT_SECONDS


def build_bot(settings: Settings) -> Bot:
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

    # app.main has finished defining its router by the time build_bot is called.
    # Register lazily here so both the normal bot and Roadmap Studio expose
    # diagnostic admin commands before the final catch-all handler.
    import app.main as bot_app

    install_admin_ping(bot_app.router)
    install_memory_debug(bot_app.router)
    return bot
