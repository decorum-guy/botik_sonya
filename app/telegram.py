from __future__ import annotations

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode

from app.config import Settings


def build_bot(settings: Settings) -> Bot:
    """Create one Bot instance with optional proxy support from .env."""
    session = AiohttpSession(proxy=settings.proxy_url)
    return Bot(
        token=settings.bot_token,
        session=session,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
