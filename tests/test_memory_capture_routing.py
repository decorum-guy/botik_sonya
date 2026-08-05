from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from aiogram.types import Chat, Message, Sticker, User, VideoNote

from app.memory_capture_middleware import MemoryCaptureMiddleware


class FakeStorage:
    def __init__(self) -> None:
        self.rows: list[dict] = []

    async def admin_session(self, admin_id: int):
        return ("memory_record", "rich") if admin_id == 7 else None

    async def memory_messages(self, memory_id: str):
        return [
            (
                index,
                row["source_chat_id"],
                row["source_message_id"],
                row["content_type"],
                row["origin_label"],
            )
            for index, row in enumerate(self.rows, start=1)
            if row["memory_id"] == memory_id
        ]

    async def add_memory_message(self, **kwargs) -> int:
        self.rows.append(kwargs)
        return len(self.rows)


def base_message(message_id: int, **kwargs) -> Message:
    return Message(
        message_id=message_id,
        date=datetime.now(UTC),
        chat=Chat(id=7, type="private"),
        from_user=User(id=7, is_bot=False, first_name="Admin"),
        **kwargs,
    )


def test_video_note_is_captured_before_router() -> None:
    storage = FakeStorage()
    middleware = MemoryCaptureMiddleware(storage)
    message = base_message(
        10,
        video_note=VideoNote(
            file_id="circle-file",
            file_unique_id="circle-unique",
            length=384,
            duration=8,
        ),
    )
    routed = False

    async def handler(event, data):
        nonlocal routed
        routed = True

    asyncio.run(middleware(handler, message, {}))

    assert routed is False
    assert len(storage.rows) == 1
    assert storage.rows[0]["content_type"] == "video_note"


def test_sticker_is_captured_before_router() -> None:
    storage = FakeStorage()
    middleware = MemoryCaptureMiddleware(storage)
    message = base_message(
        11,
        sticker=Sticker(
            file_id="sticker-file",
            file_unique_id="sticker-unique",
            type="regular",
            width=512,
            height=512,
            is_animated=False,
            is_video=True,
        ),
    )

    async def handler(event, data):  # pragma: no cover - must not be called
        raise AssertionError("rich memory update reached router")

    asyncio.run(middleware(handler, message, {}))

    assert len(storage.rows) == 1
    assert storage.rows[0]["content_type"] == "sticker"


def test_commands_continue_to_router() -> None:
    storage = FakeStorage()
    middleware = MemoryCaptureMiddleware(storage)
    message = base_message(12, text="/memory_save")

    async def handler(event, data):
        return "routed"

    result = asyncio.run(middleware(handler, message, {}))

    assert result == "routed"
    assert storage.rows == []
