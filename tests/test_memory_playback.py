from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

from aiogram.exceptions import TelegramBadRequest

import app.engine as engine_module
from app.engine import QuestEngine
from app.models import MemoryAction


class FakeStorage:
    def __init__(self, messages) -> None:
        self._messages = messages

    async def memory_messages(self, memory_id: str):
        return list(self._messages)


class FakeBot:
    def __init__(self, *, fail_forward: bool = False) -> None:
        self.fail_forward = fail_forward
        self.sent_texts: list[tuple[int, str]] = []
        self.forwarded: list[tuple[int, int, int]] = []
        self.copied: list[tuple[int, int, int]] = []

    async def send_message(self, chat_id: int, text: str):
        self.sent_texts.append((chat_id, text))
        return SimpleNamespace(message_id=len(self.sent_texts))

    async def forward_message(self, *, chat_id: int, from_chat_id: int, message_id: int):
        if self.fail_forward:
            raise TelegramBadRequest(
                method=SimpleNamespace(__api_method__="forwardMessage"),
                message="message can't be forwarded",
            )
        self.forwarded.append((chat_id, from_chat_id, message_id))
        return SimpleNamespace(message_id=message_id)

    async def copy_message(self, *, chat_id: int, from_chat_id: int, message_id: int):
        self.copied.append((chat_id, from_chat_id, message_id))
        return SimpleNamespace(message_id=message_id)


def memory_action() -> MemoryAction:
    return MemoryAction(
        type="memory_reconstruction",
        memory_id="memory-1",
        number=1,
        total=1,
        date_text="Когда-то",
        intro="",
        outro="",
    )


def test_memory_uses_random_delays_only_between_messages(monkeypatch) -> None:
    messages = [
        (1, 100, 10, "text", None),
        (2, 100, 11, "video_note", None),
        (3, 100, 12, "sticker", None),
    ]
    bot = FakeBot()
    storage = FakeStorage(messages)
    quest = QuestEngine(bot, storage, SimpleNamespace(), Path("."))
    delays = iter((1.0, 3.5))
    sleeps: list[float] = []

    monkeypatch.setattr(engine_module.random, "uniform", lambda low, high: next(delays))

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr(engine_module.asyncio, "sleep", fake_sleep)

    asyncio.run(quest.play_memory(777, memory_action()))

    assert bot.forwarded == [
        (777, 100, 10),
        (777, 100, 11),
        (777, 100, 12),
    ]
    assert sleeps == [1.0, 3.5]


def test_memory_falls_back_to_copy_message() -> None:
    messages = [(1, 100, 10, "sticker", None)]
    bot = FakeBot(fail_forward=True)
    storage = FakeStorage(messages)
    quest = QuestEngine(bot, storage, SimpleNamespace(), Path("."))

    asyncio.run(quest.preview_memory(777, "memory-1"))

    assert bot.forwarded == []
    assert bot.copied == [(777, 100, 10)]


def test_random_delay_stays_in_required_range() -> None:
    for _ in range(100):
        delay = engine_module.memory_message_delay_seconds()
        assert 1.0 <= delay <= 3.5
