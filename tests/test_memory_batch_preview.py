from __future__ import annotations

import asyncio
from types import SimpleNamespace

from app.memory_batch_preview import send_memory_batch_preview
from app.models import MemoryAction


class FakeStorage:
    def __init__(self, messages) -> None:
        self._messages = list(messages)

    async def memory_messages(self, memory_id: str):
        return list(self._messages)


class FakeBot:
    def __init__(self) -> None:
        self.sent_messages: list[dict] = []
        self.forward_batches: list[dict] = []

    async def send_message(self, chat_id: int, text: str, **kwargs):
        message_id = len(self.sent_messages) + 1
        self.sent_messages.append(
            {
                "chat_id": chat_id,
                "text": text,
                "kwargs": kwargs,
                "message_id": message_id,
            }
        )
        return SimpleNamespace(message_id=message_id)

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


def roadmap_with_memory(memory_id: str = "memory-1"):
    action = MemoryAction(
        type="memory_reconstruction",
        memory_id=memory_id,
        number=2,
        total=4,
        date_text="5 июля 2024",
        title="ВОССТАНОВЛЕНИЕ ВОСПОМИНАНИЯ",
        intro="Начинаем",
        outro="Это было тепло",
    )
    return SimpleNamespace(steps=[SimpleNamespace(actions=[action])])


def test_batch_preview_forwards_all_messages_in_one_request_and_replies_to_header() -> None:
    storage = FakeStorage(
        [
            (1, 777, 10, "text", None),
            (2, 777, 11, "video_note", None),
            (3, 777, 12, "sticker", None),
        ]
    )
    bot = FakeBot()

    result = asyncio.run(
        send_memory_batch_preview(
            bot=bot,
            storage=storage,
            roadmap=roadmap_with_memory(),
            destination_chat_id=123,
            memory_id="memory-1",
        )
    )

    assert result.stored_count == 3
    assert result.forwarded_count == 3
    assert result.batch_count == 1
    assert bot.forward_batches == [
        {
            "chat_id": 123,
            "from_chat_id": 777,
            "message_ids": [10, 11, 12],
        }
    ]

    header = bot.sent_messages[0]
    finish = bot.sent_messages[-1]
    assert "5 июля 2024" in header["text"]
    assert "Воспоминание восстановлено" in finish["text"]
    assert "Воспоминание завершено" not in finish["text"]
    reply_parameters = finish["kwargs"]["reply_parameters"]
    assert reply_parameters.message_id == header["message_id"]
    assert reply_parameters.allow_sending_without_reply is True


def test_batch_preview_splits_more_than_one_hundred_messages() -> None:
    messages = [
        (position, 777, 1000 + position, "text", None)
        for position in range(1, 206)
    ]
    storage = FakeStorage(messages)
    bot = FakeBot()

    result = asyncio.run(
        send_memory_batch_preview(
            bot=bot,
            storage=storage,
            roadmap=roadmap_with_memory(),
            destination_chat_id=123,
            memory_id="memory-1",
        )
    )

    assert result.stored_count == 205
    assert result.forwarded_count == 205
    assert result.batch_count == 3
    assert [len(item["message_ids"]) for item in bot.forward_batches] == [100, 100, 5]
    assert bot.forward_batches[0]["message_ids"][0] == 1001
    assert bot.forward_batches[-1]["message_ids"][-1] == 1205
