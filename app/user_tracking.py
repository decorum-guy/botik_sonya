from __future__ import annotations

from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from app.memory_capture_middleware import MemoryCaptureMiddleware
from app.memory_debug import memory_debug
from app.storage import Storage


class UserTrackingMiddleware(BaseMiddleware):
    """Persist private users, log updates and protect memory capture in Studio."""

    def __init__(self, storage: Storage) -> None:
        self.storage = storage
        self.memory_capture = MemoryCaptureMiddleware(storage)

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

        if isinstance(event, Message) and event.from_user is not None:
            update = data.get("event_update")
            await memory_debug.record_incoming(
                event.from_user.id,
                event,
                update_id=getattr(update, "update_id", None),
            )

        # Roadmap Studio includes its own routers before app.main. Capturing here
        # guarantees that stickers, video notes and every other message type are
        # stored before a test-input filter can consume the update.
        return await self.memory_capture(handler, event, data)
