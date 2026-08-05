from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject

from app.memory_capture import capture_memory_message, is_command_message
from app.memory_debug import memory_debug
from app.storage import Storage


_MEMORY_SESSION_MODES = {"memory_record", "memory_editor", "memory_manual"}


def finish_command_for_mode(mode: str) -> str:
    if mode == "memory_editor":
        return "/end"
    if mode == "memory_manual":
        return "/memory_save"
    return "/memory_done"


class MemoryCaptureMiddleware(BaseMiddleware):
    """Capture every Telegram message type before another route can consume it."""

    def __init__(self, storage: Storage) -> None:
        self.storage = storage

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if (
            not isinstance(event, Message)
            or event.from_user is None
            or is_command_message(event)
        ):
            return await handler(event, data)

        session = await self.storage.admin_session(event.from_user.id)
        if session is None or session[0] not in _MEMORY_SESSION_MODES:
            return await handler(event, data)

        mode, memory_id = session
        await memory_debug.record(
            event.from_user.id,
            "capture_middleware_claimed",
            message_id=event.message_id,
            content_type=str(event.content_type),
            memory_id=memory_id,
            session_mode=mode,
        )
        await capture_memory_message(
            self.storage,
            event,
            memory_id,
            finish_command=finish_command_for_mode(mode),
        )

        # Do not let Roadmap Studio test-input handlers or a generic catch-all
        # process the same sticker, video note, photo or other memory fragment.
        return None


def install_memory_capture(router, storage: Storage) -> None:
    if getattr(router, "_memory_capture_installed", False):
        return
    router.message.outer_middleware(MemoryCaptureMiddleware(storage))
    router._memory_capture_installed = True
