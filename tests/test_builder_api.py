from __future__ import annotations

import pytest

from app.builder_api import BuilderApiError, prepare_test_roadmap
from app.models import AskInputAction, ButtonsAction, Roadmap


def roadmap() -> Roadmap:
    return Roadmap.model_validate(
        {
            "meta": {
                "version": 1,
                "title": "Test",
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
                            "text": "Hello",
                            "parse_mode": "HTML",
                            "disable_notification": False,
                        },
                        {
                            "type": "ask_input",
                            "prompt": "Answer",
                            "parse_mode": "HTML",
                            "validator": {"type": "any"},
                            "wrong_answers": ["Wrong"],
                            "success_text": "Right",
                            "next_step": "finish",
                        },
                        {
                            "type": "buttons",
                            "text": "Choose",
                            "parse_mode": "HTML",
                            "columns": 1,
                            "buttons": [
                                {
                                    "text": "Next",
                                    "id": "next",
                                    "style": "primary",
                                    "next_step": "finish",
                                    "answer_text": "",
                                }
                            ],
                        },
                    ],
                },
                {
                    "id": "finish",
                    "title": "Finish",
                    "actions": [
                        {
                            "type": "goto",
                            "step_id": "intro",
                        }
                    ],
                },
            ],
        }
    )


def test_full_and_step_keep_original_roadmap() -> None:
    source = roadmap()
    full, full_start = prepare_test_roadmap(source, "full")
    step, step_start = prepare_test_roadmap(source, "step", step_id="finish")

    assert full is source
    assert full_start == "intro"
    assert step is source
    assert step_start == "finish"


def test_single_input_block_stops_after_answer() -> None:
    single, start = prepare_test_roadmap(
        roadmap(),
        "action",
        step_id="intro",
        action_index=1,
    )

    action = single.step(start).actions[0]
    assert isinstance(action, AskInputAction)
    assert action.next_step is None
    assert len(single.steps) == 1


def test_single_buttons_block_removes_transitions() -> None:
    single, start = prepare_test_roadmap(
        roadmap(),
        "action",
        step_id="intro",
        action_index=2,
    )

    action = single.step(start).actions[0]
    assert isinstance(action, ButtonsAction)
    assert all(button.next_step is None for button in action.buttons)


def test_single_goto_block_requires_step_preview() -> None:
    with pytest.raises(BuilderApiError, match="Запусти этап целиком"):
        prepare_test_roadmap(
            roadmap(),
            "action",
            step_id="finish",
            action_index=0,
        )
