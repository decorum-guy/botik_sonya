from __future__ import annotations

import asyncio
from pathlib import Path

import app.engine as engine_module
from aiogram.exceptions import TelegramRetryAfter
from aiogram.methods import SendMessageDraft

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


class FloodOnceBot(FakeBot):
    def __init__(self) -> None:
        super().__init__()
        self.draft_attempts = 0

    async def send_message_draft(self, *, chat_id: int, draft_id: int, text: str) -> bool:
        self.draft_attempts += 1
        if self.draft_attempts == 1:
            raise TelegramRetryAfter(
                method=SendMessageDraft(chat_id=chat_id, draft_id=draft_id, text=text),
                message="Too Many Requests",
                retry_after=0,
            )
        return await super().send_message_draft(
            chat_id=chat_id,
            draft_id=draft_id,
            text=text,
        )


class FakeStorage:
    pass


async def no_sleep(_: float) -> None:
    return None


def configure_fast_test(monkeypatch) -> None:
    monkeypatch.setattr(engine_module.asyncio, "sleep", no_sleep)
    monkeypatch.setattr(engine_module, "DRAFT_MIN_REQUEST_INTERVAL_SECONDS", 0)


def test_text_action_remains_instant_by_default() -> None:
    action = SendTextAction.model_validate({"type": "send_text", "text": "Привет"})

    assert action.delivery_mode == "instant"
    assert action.stream_segments == []


def test_character_stream_uses_draft_and_persists_final_message(monkeypatch) -> None:
    configure_fast_test(monkeypatch)
    monkeypatch.setattr(engine_module, "DRAFT_FLUSH_INTERVAL_SECONDS", 0)
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


def test_stream_segments_are_appended_to_one_draft(monkeypatch) -> None:
    configure_fast_test(monkeypatch)
    monkeypatch.setattr(engine_module, "DRAFT_FLUSH_INTERVAL_SECONDS", 0)
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


def test_character_stream_batches_api_updates(monkeypatch) -> None:
    configure_fast_test(monkeypatch)
    monkeypatch.setattr(engine_module, "DRAFT_FLUSH_INTERVAL_SECONDS", 0.75)
    bot = FakeBot()
    engine = QuestEngine(bot, FakeStorage(), None, Path("."))  # type: ignore[arg-type]
    text = "Сигнал зафиксирован. Ты находишься в ресторане."
    action = SendTextAction.model_validate(
        {
            "type": "send_text",
            "text": text,
            "parse_mode": "none",
            "delivery_mode": "characters",
            "typing_speed_seconds": 0.09,
        }
    )

    asyncio.run(engine._send_text(123, action))

    assert 1 <= len(bot.drafts) < len(text) / 2
    assert bot.messages[-1][1] == text


def test_retry_after_does_not_lose_final_message(monkeypatch) -> None:
    configure_fast_test(monkeypatch)
    monkeypatch.setattr(engine_module, "DRAFT_FLUSH_INTERVAL_SECONDS", 0)
    bot = FloodOnceBot()
    engine = QuestEngine(bot, FakeStorage(), None, Path("."))  # type: ignore[arg-type]
    action = SendTextAction.model_validate(
        {
            "type": "send_text",
            "text": "Сигнал зафиксирован.",
            "parse_mode": "none",
            "delivery_mode": "characters",
            "typing_speed_seconds": 0.09,
        }
    )

    asyncio.run(engine._send_text(123, action))

    assert bot.draft_attempts > 1
    assert bot.messages[-1][1] == action.text
