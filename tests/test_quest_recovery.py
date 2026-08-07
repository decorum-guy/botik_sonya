from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

from app.engine import QuestEngine
from app.models import Roadmap
from app.storage import Storage

PARTICIPANT_CHAT_ID = 777
ADMIN_CHAT_ID = 999


class FlakyBot:
    def __init__(self, *, fail_second_once: bool = True) -> None:
        self.fail_second_once = fail_second_once
        self.messages: list[dict] = []

    async def send_message(self, chat_id: int, text: str, **kwargs):
        if (
            chat_id == PARTICIPANT_CHAT_ID
            and text == "Второе сообщение"
            and self.fail_second_once
        ):
            self.fail_second_once = False
            raise RuntimeError("synthetic unexpected Telegram failure")

        message = SimpleNamespace(message_id=len(self.messages) + 1)
        self.messages.append(
            {
                "chat_id": chat_id,
                "text": text,
                "kwargs": kwargs,
                "message": message,
            }
        )
        return message


ROADMAP = Roadmap.model_validate(
    {
        "meta": {
            "version": 1,
            "title": "Recovery test",
            "entry_step_id": "intro",
            "intro_step_id": "intro",
        },
        "steps": [
            {
                "id": "intro",
                "title": "Intro",
                "actions": [
                    {
                        "type": "send_text",
                        "text": "Первое сообщение",
                    },
                    {
                        "type": "send_text",
                        "text": "Второе сообщение",
                    },
                ],
            }
        ],
    }
)


def participant_texts(bot: FlakyBot) -> list[str]:
    return [
        item["text"]
        for item in bot.messages
        if item["chat_id"] == PARTICIPANT_CHAT_ID
    ]


def test_unexpected_failure_pauses_and_continue_resumes_from_checkpoint(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        storage = Storage(tmp_path / "bot.db")
        await storage.init()
        bot = FlakyBot()
        engine = QuestEngine(bot, storage, ROADMAP, tmp_path)
        engine.configure_quest_recovery(lambda: ADMIN_CHAT_ID)

        await engine.start(PARTICIPANT_CHAT_ID)

        progress = await storage.get_progress(PARTICIPANT_CHAT_ID)
        assert progress is not None
        assert progress.step_id == "intro"
        assert progress.action_index == 1
        assert participant_texts(bot) == ["Первое сообщение"]

        failure = await engine.quest_failure(PARTICIPANT_CHAT_ID)
        assert failure is not None
        assert failure["step_id"] == "intro"
        assert failure["action_index"] == 1
        assert failure["action_type"] == "send_text"
        assert failure["exception_type"] == "RuntimeError"
        assert any(
            item["chat_id"] == ADMIN_CHAT_ID
            and "аварийную паузу" in item["text"]
            and "/continue" in item["text"]
            for item in bot.messages
        )

        result = await engine.continue_quest(PARTICIPANT_CHAT_ID)

        assert result.status == "completed"
        assert participant_texts(bot) == [
            "Первое сообщение",
            "Второе сообщение",
        ]
        assert participant_texts(bot).count("Первое сообщение") == 1
        assert await storage.get_progress(PARTICIPANT_CHAT_ID) is None
        assert await engine.quest_failure(PARTICIPANT_CHAT_ID) is None

    asyncio.run(scenario())


def test_continue_after_process_restart_uses_persisted_progress(tmp_path: Path) -> None:
    async def scenario() -> None:
        storage = Storage(tmp_path / "bot.db")
        await storage.init()
        await storage.set_progress(PARTICIPANT_CHAT_ID, "intro", 1)

        bot = FlakyBot(fail_second_once=False)
        restarted_engine = QuestEngine(bot, storage, ROADMAP, tmp_path)
        restarted_engine.configure_quest_recovery(lambda: ADMIN_CHAT_ID)

        result = await restarted_engine.continue_quest(PARTICIPANT_CHAT_ID)

        assert result.status == "completed"
        assert participant_texts(bot) == ["Второе сообщение"]
        assert await storage.get_progress(PARTICIPANT_CHAT_ID) is None

    asyncio.run(scenario())


def test_continue_does_not_duplicate_a_normal_user_wait(tmp_path: Path) -> None:
    async def scenario() -> None:
        storage = Storage(tmp_path / "bot.db")
        await storage.init()
        await storage.set_progress(
            PARTICIPANT_CHAT_ID,
            "intro",
            1,
            waiting={"kind": "buttons"},
        )

        bot = FlakyBot(fail_second_once=False)
        engine = QuestEngine(bot, storage, ROADMAP, tmp_path)
        engine.configure_quest_recovery(lambda: ADMIN_CHAT_ID)

        result = await engine.continue_quest(PARTICIPANT_CHAT_ID)

        assert result.status == "waiting"
        assert participant_texts(bot) == []
        progress = await storage.get_progress(PARTICIPANT_CHAT_ID)
        assert progress is not None
        assert progress.waiting == {"kind": "buttons"}

    asyncio.run(scenario())
