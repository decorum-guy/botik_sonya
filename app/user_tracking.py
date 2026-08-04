from __future__ import annotations

from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from app.storage import Storage


class UserTrackingMiddleware(BaseMiddleware):
    """Persist every private user who sends a message or presses a bot button."""

    def __init__(self, storage: Storage) -> None:
        self.storage = storage

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = getattr(event, "from_user", None)
        message: Message | None
        if isinstance(event, Message):
            message = event
        elif isinstance(event, CallbackQuery) and isinstance(event.message, Message):
            message = event.message
        else:
            message = None

        chat = message.chat if message is not None else None
        if user is not None and chat is not None and chat.type == "private":
            await self.storage.remember_user(
                user_id=user.id,
                chat_id=chat.id,
                username=user.username,
                first_name=user.first_name,
                last_name=user.last_name,
            )

        return await handler(event, data)
