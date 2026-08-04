from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.engine import QuestEngine
from app.models import ButtonSpec, Roadmap


class FakeBot:
    async def send_message(self, *args, **kwargs) -> None:
        return None


class FakeStorage:
    def __init__(self) -> None:
        self.progress = SimpleNamespace(
            step_id="buttons",
            action_index=0,
            waiting={"kind": "buttons"},
            wrong_index=0,
        )

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
            step_id=step_id,
            action_index=action_index,
            waiting=waiting,
            wrong_index=wrong_index,
        )

    async def clear_progress(self, chat_id: int) -> None:
        self.progress = None


def test_old_button_gets_default_callback_text() -> None:
    button = ButtonSpec.model_validate({"text": "Продолжить", "id": "continue"})

    assert button.callback_text == "Принято"


def test_callback_text_is_limited_to_telegram_limit() -> None:
    with pytest.raises(ValidationError):
        ButtonSpec.model_validate(
            {
                "text": "Продолжить",
                "id": "continue",
                "callback_text": "x" * 201,
            }
        )


def test_engine_returns_selected_button_callback_text() -> None:
    roadmap = Roadmap.model_validate(
        {
            "meta": {
                "version": 1,
                "title": "Test",
                "entry_step_id": "buttons",
                "intro_step_id": None,
            },
            "steps": [
                {
                    "id": "buttons",
                    "title": "Buttons",
                    "actions": [
                        {
                            "type": "buttons",
                            "text": "Choose",
                            "buttons": [
                                {
                                    "text": "Да",
                                    "id": "yes",
                                    "callback_text": "Верный выбор ✨",
                                }
                            ],
                        }
                    ],
                }
            ],
        }
    )
    engine = QuestEngine(FakeBot(), FakeStorage(), roadmap, Path("."))

    ok, callback_text = asyncio.run(engine.handle_button(123, "yes"))

    assert ok is True
    assert callback_text == "Верный выбор ✨"
