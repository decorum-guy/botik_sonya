from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import app.engine as engine_module
from app.engine import QuestEngine
from app.memory_modes import (
    MEMORY_MODE_BATCH,
    MEMORY_MODE_STREAM,
    get_memory_mode,
    set_memory_mode,
)
from app.models import MemoryAction


class FakeStorage:
    def __init__(self, messages, *, mode: str | None = None) -> None:
        self._messages = list(messages)
        self.settings: dict[str, str] = {}
        if mode is not None:
            self.settings["memory_mode:memory-1"] = mode

    async def memory_messages(self, memory_id: str):
        return list(self._messages)

    async def get_setting(self, key: str):
        return self.settings.get(key)

    async def set_setting(self, key: str, value: str) -> None:
        self.settings[key] = value

    async def list_memories(self):
        return [("memory-1", len(self._messages))]


class FakeBot:
    def __init__(self) -> None:
        self.sent_messages: list[dict] = []
        self.forwarded: list[tuple[int, int, int]] = []
        self.forward_batches: list[dict] = []
        self.copied: list[tuple[int, int, int]] = []

    async def send_message(self, chat_id: int, text: str, **kwargs):
        message_id = 900 + len(self.sent_messages)
        self.sent_messages.append(
            {
                "chat_id": chat_id,
                "text": text,
                "kwargs": kwargs,
                "message_id": message_id,
            }
        )
        return SimpleNamespace(message_id=message_id)

    async def forward_message(self, *, chat_id: int, from_chat_id: int, message_id: int):
        self.forwarded.append((chat_id, from_chat_id, message_id))
        return SimpleNamespace(message_id=message_id + 1000)

    async def forward_messages(
        self,
        *,
        chat_id: int,
        from_chat_id: int,
        message_ids: list[int],
    ):
        self.forward_batches.append(
            {
                "chat_id": chat_id,
                "from_chat_id": from_chat_id,
                "message_ids": list(message_ids),
            }
        )
        return [SimpleNamespace(message_id=value + 1000) for value in message_ids]

    async def copy_message(self, *, chat_id: int, from_chat_id: int, message_id: int):
        self.copied.append((chat_id, from_chat_id, message_id))
        return SimpleNamespace(message_id=message_id + 2000)


def memory_action() -> MemoryAction:
    return MemoryAction(
        type="memory_reconstruction",
        memory_id="memory-1",
        number=2,
        total=4,
        date_text="5 июля 2024",
        title="ВОССТАНОВЛЕНИЕ ВОСПОМИНАНИЯ",
        intro="Начинаем",
        outro="Это было тепло",
    )


def roadmap():
    return SimpleNamespace(
        steps=[SimpleNamespace(actions=[memory_action()])],
    )


def test_legacy_memory_defaults_to_stream_and_finishes_with_reply(monkeypatch) -> None:
    storage = FakeStorage(
        [
            (1, 100, 10, "text", None),
            (2, 100, 11, "video_note", None),
            (3, 100, 12, "sticker", None),
        ]
    )
    bot = FakeBot()
    quest = QuestEngine(bot, storage, roadmap(), Path("."))
    sleeps: list[float] = []
    delays = iter((1.0, 3.5))

    monkeypatch.setattr(engine_module.random, "uniform", lambda low, high: next(delays))

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr(engine_module.asyncio, "sleep", fake_sleep)

    count = asyncio.run(quest.play_memory(777, memory_action()))

    assert count == 3
    assert bot.forwarded == [
        (777, 100, 10),
        (777, 100, 11),
        (777, 100, 12),
    ]
    assert bot.forward_batches == []
    assert sleeps == [1.0, 3.5]

    header = bot.sent_messages[0]
    finish = bot.sent_messages[-1]
    assert "5 июля 2024" in header["text"]
    assert "Воспоминание восстановлено" in finish["text"]
    assert "Воспоминание завершено" not in finish["text"]
    assert finish["kwargs"]["reply_parameters"].message_id == header["message_id"]


def test_batch_memory_uses_one_forward_messages_call_without_delays(monkeypatch) -> None:
    storage = FakeStorage(
        [
            (1, 100, 10, "text", None),
            (2, 100, 11, "text", None),
            (3, 100, 12, "sticker", None),
        ],
        mode=MEMORY_MODE_BATCH,
    )
    bot = FakeBot()
    quest = QuestEngine(bot, storage, roadmap(), Path("."))
    sleeps: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr(engine_module.asyncio, "sleep", fake_sleep)

    count = asyncio.run(quest.play_memory(777, memory_action()))

    assert count == 3
    assert bot.forwarded == []
    assert bot.forward_batches == [
        {
            "chat_id": 777,
            "from_chat_id": 100,
            "message_ids": [10, 11, 12],
        }
    ]
    assert sleeps == []
    assert bot.sent_messages[-1]["kwargs"]["reply_parameters"].message_id == 900


def test_preview_uses_saved_mode_and_full_memory_header() -> None:
    storage = FakeStorage(
        [(1, 100, 10, "text", None)],
        mode=MEMORY_MODE_BATCH,
    )
    bot = FakeBot()
    quest = QuestEngine(bot, storage, roadmap(), Path("."))

    count = asyncio.run(quest.preview_memory(777, "memory-1"))

    assert count == 1
    assert bot.forward_batches[0]["message_ids"] == [10]
    assert "5 июля 2024" in bot.sent_messages[0]["text"]
    assert "Начинаем" in [item["text"] for item in bot.sent_messages]
    assert "Это было тепло" in [item["text"] for item in bot.sent_messages]


def test_memory_mode_setting_is_persistent_and_validated() -> None:
    storage = FakeStorage([])

    assert asyncio.run(get_memory_mode(storage, "memory-1")) == MEMORY_MODE_STREAM

    asyncio.run(set_memory_mode(storage, "memory-1", MEMORY_MODE_BATCH))
    assert asyncio.run(get_memory_mode(storage, "memory-1")) == MEMORY_MODE_BATCH

    try:
        asyncio.run(set_memory_mode(storage, "memory-1", "wrong"))
    except ValueError:
        pass
    else:  # pragma: no cover - validation invariant
        raise AssertionError("invalid memory mode was accepted")
