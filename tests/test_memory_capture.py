from __future__ import annotations

import asyncio
from types import SimpleNamespace

from app.memory_capture import (
    capture_memory_message,
    custom_emoji_count,
    memory_content_label,
)


class FakeStorage:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def add_memory_message(self, **kwargs) -> int:
        self.calls.append(kwargs)
        return len(self.calls)


class FakeMessage:
    def __init__(
        self,
        *,
        content_type: str,
        text: str | None = None,
        video_note=None,
        sticker=None,
        entities=None,
        caption_entities=None,
        forward_origin=None,
    ) -> None:
        self.content_type = content_type
        self.text = text
        self.caption = None
        self.video_note = video_note
        self.sticker = sticker
        self.entities = entities
        self.caption_entities = caption_entities
        self.forward_origin = forward_origin
        self.chat = SimpleNamespace(id=123)
        self.message_id = 456
        self.answers: list[str] = []

    async def answer(self, text: str) -> None:
        self.answers.append(text)


def test_video_note_is_captured_without_forward_origin() -> None:
    storage = FakeStorage()
    message = FakeMessage(
        content_type="video_note",
        video_note=SimpleNamespace(file_id="circle"),
        forward_origin=None,
    )

    position = asyncio.run(
        capture_memory_message(
            storage,
            message,
            "memory-1",
            finish_command="/memory_done",
        )
    )

    assert position == 1
    assert storage.calls[0]["content_type"] == "video_note"
    assert storage.calls[0]["origin_label"].startswith("NoForwardOrigin|кружок")
    assert "кружок" in message.answers[0]


def test_premium_sticker_is_detected() -> None:
    sticker = SimpleNamespace(
        type="regular",
        premium_animation=SimpleNamespace(file_id="premium-effect"),
        is_video=False,
        is_animated=True,
    )
    message = FakeMessage(content_type="sticker", sticker=sticker)

    assert memory_content_label(message) == "premium-стикер"


def test_custom_emoji_entities_are_detected() -> None:
    entities = [
        SimpleNamespace(type=SimpleNamespace(value="custom_emoji")),
        SimpleNamespace(type="bold"),
        SimpleNamespace(type="custom_emoji"),
    ]
    message = FakeMessage(content_type="text", text="🙂🙂", entities=entities)

    assert custom_emoji_count(message) == 2
    assert memory_content_label(message) == "текст с пользовательскими эмоджи ×2"


def test_command_is_not_added_to_memory() -> None:
    storage = FakeStorage()
    message = FakeMessage(content_type="text", text="/ping")

    position = asyncio.run(
        capture_memory_message(
            storage,
            message,
            "memory-1",
            finish_command="/memory_done",
        )
    )

    assert position is None
    assert storage.calls == []
    assert "не добавлена" in message.answers[0]
