from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

from app.engine import QuestEngine
from app.models import MemoryAction, SendTextAction


class FakeStorage:
    def __init__(self) -> None:
        self.progress = SimpleNamespace(
            chat_id=777,
            step_id="step-1",
            action_index=0,
            waiting=None,
            wrong_index=0,
        )
        self.messages = [(1, 100, 10, "text", None)]

    async def get_progress(self, chat_id: int):
        return self.progress

    async def set_progress(
        self,
        chat_id: int,
        step_id: str,
        action_index: int,
        waiting=None,
        wrong_index: int = 0,
    ) -> None:
        self.progress = SimpleNamespace(
            chat_id=chat_id,
            step_id=step_id,
            action_index=action_index,
            waiting=waiting,
            wrong_index=wrong_index,
        )

    async def clear_progress(self, chat_id: int) -> None:
        self.progress = None

    async def memory_messages(self, memory_id: str):
        return list(self.messages)

    async def get_setting(self, key: str):
        return "batch"


class FakeBot:
    def __init__(self) -> None:
        self.sent_messages: list[dict] = []
        self.forward_batches: list[dict] = []

    async def send_message(self, chat_id: int, text: str, **kwargs):
        message = SimpleNamespace(message_id=len(self.sent_messages) + 1)
        self.sent_messages.append(
            {
                "chat_id": chat_id,
                "text": text,
                "kwargs": kwargs,
                "message": message,
            }
        )
        return message

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
        return [SimpleNamespace(message_id=1000 + value) for value in message_ids]

    async def forward_message(self, **kwargs):
        return SimpleNamespace(message_id=2000)

    async def copy_message(self, **kwargs):
        return SimpleNamespace(message_id=3000)


class FakeRoadmap:
    def __init__(self) -> None:
        self._step = SimpleNamespace(
            id="step-1",
            actions=[
                MemoryAction(
                    type="memory_reconstruction",
                    memory_id="memory-1",
                    number=1,
                    total=1,
                    date_text="5 июля 2024",
                    intro="",
                    outro="",
                ),
                SendTextAction(
                    type="send_text",
                    text="Сюжет продолжается",
                ),
            ],
        )

    def step(self, step_id: str):
        assert step_id == self._step.id
        return self._step


def test_quest_waits_for_read_button_and_survives_engine_restart() -> None:
    async def scenario() -> None:
        storage = FakeStorage()
        bot = FakeBot()
        roadmap = FakeRoadmap()
        engine = QuestEngine(bot, storage, roadmap, Path("."))

        await engine._execute(777)

        assert storage.progress is not None
        assert storage.progress.action_index == 0
        assert storage.progress.waiting["kind"] == "memory_ack"
        assert bot.forward_batches == [
            {
                "chat_id": 777,
                "from_chat_id": 100,
                "message_ids": [10],
            }
        ]
        assert all(
            item["text"] != "Сюжет продолжается"
            for item in bot.sent_messages
        )

        header = bot.sent_messages[0]
        finish = bot.sent_messages[-1]
        assert "Воспоминание восстановлено" in finish["text"]
        assert "Воспоминание завершено" not in finish["text"]
        reply_parameters = finish["kwargs"]["reply_parameters"]
        assert reply_parameters.message_id == header["message"].message_id

        keyboard = finish["kwargs"]["reply_markup"]
        button = keyboard.inline_keyboard[0][0]
        assert button.text == "Прочитала"
        assert button.callback_data.startswith("quest:memory_ack:")

        # A fresh engine instance must be able to resume from the persisted
        # waiting state after a process restart.
        restarted_engine = QuestEngine(bot, storage, roadmap, Path("."))
        button_id = button.callback_data.removeprefix("quest:")
        ok, note = await restarted_engine.handle_button(777, button_id)
        assert ok is True
        assert note == "Продолжаем ✨"

        for _ in range(5):
            await asyncio.sleep(0)

        assert any(
            item["text"] == "Сюжет продолжается"
            for item in bot.sent_messages
        )
        assert storage.progress is None

        ok_again, note_again = await restarted_engine.handle_button(777, button_id)
        assert ok_again is False
        assert note_again == "Эта кнопка уже неактивна."

    asyncio.run(scenario())
