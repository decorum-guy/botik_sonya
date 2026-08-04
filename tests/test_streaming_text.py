from __future__ import annotations

import asyncio
from pathlib import Path

from app.engine import QuestEngine
from app.models import SendTextAction


class FakeBot:
    def __init__(self) -> None:
        self.drafts: list[str] = []
        self.messages: list[tuple[int, str, dict]] = []

    async def send_message_draft(self, *, chat_id: int, draft_id: int, text: str) -> bool:
        assert chat_id == 123
        assert draft_id > 0
        self.drafts.append(text)
        return True

    async def send_message(self, chat_id: int, text: str, **kwargs) -> None:
        self.messages.append((chat_id, text, kwargs))


class FakeStorage:
    pass


def test_text_action_remains_instant_by_default() -> None:
    action = SendTextAction.model_validate({"type": "send_text", "text": "Привет"})

    assert action.delivery_mode == "instant"
    assert action.stream_segments == []


def test_character_stream_uses_draft_and_persists_final_message() -> None:
    bot = FakeBot()
    engine = QuestEngine(bot, FakeStorage(), None, Path("."))  # type: ignore[arg-type]
    action = SendTextAction.model_validate(
        {
            "type": "send_text",
            "text": "<b>Да</b>",
            "parse_mode": "HTML",
            "delivery_mode": "characters",
            "typing_speed_seconds": 0.03,
        }
    )

    asyncio.run(engine._send_text(123, action))

    assert bot.drafts == ["Д", "Да"]
    assert bot.messages[0][1] == "<b>Да</b>"


def test_stream_segments_are_appended_to_one_draft() -> None:
    bot = FakeBot()
    engine = QuestEngine(bot, FakeStorage(), None, Path("."))  # type: ignore[arg-type]
    action = SendTextAction.model_validate(
        {
            "type": "send_text",
            "text": "Практически… я больше не уверен.",
            "parse_mode": "none",
            "delivery_mode": "words",
            "typing_speed_seconds": 0.03,
            "stream_segments": [
                {"text": "Практически… ", "pause_after_seconds": 0},
                {"text": "я больше не уверен.", "pause_after_seconds": 0},
            ],
        }
    )

    asyncio.run(engine._send_text(123, action))

    assert bot.drafts[-1] == "Практически… я больше не уверен."
    assert bot.messages[-1][1] == action.text
