from __future__ import annotations

from app.models import AskInputAction, ButtonsAction, GotoAction, Roadmap


class BuilderApiError(ValueError):
    """A user-facing error raised by the local Roadmap Studio test API."""


def prepare_test_roadmap(
    roadmap: Roadmap,
    scope: str,
    step_id: str | None = None,
    action_index: int | None = None,
) -> tuple[Roadmap, str]:
    """Prepare a full, step, or single-action roadmap for a test run."""
    if scope == "full":
        return roadmap, roadmap.meta.entry_step_id

    if not step_id:
        raise BuilderApiError("Не выбран этап для тестового запуска.")
    try:
        step = roadmap.step(step_id)
    except KeyError as exc:
        raise BuilderApiError(f"Этап {step_id!r} не найден.") from exc

    if scope == "step":
        return roadmap, step.id

    if scope != "action":
        raise BuilderApiError("Неизвестный режим тестового запуска.")
    if action_index is None or action_index < 0 or action_index >= len(step.actions):
        raise BuilderApiError("Не выбран блок для тестового запуска.")

    action = step.actions[action_index].model_copy(deep=True)
    if isinstance(action, GotoAction):
        raise BuilderApiError(
            "Блок «Переход» сам ничего не отправляет. Запусти этап целиком, чтобы проверить переход."
        )

    # A single-block preview must stop after the selected block instead of
    # following its configured links into the rest of the scenario.
    if isinstance(action, AskInputAction):
        action.next_step = None
    elif isinstance(action, ButtonsAction):
        for button in action.buttons:
            button.next_step = None

    test_step_id = "__builder_single_action__"
    test_data = {
        "meta": {
            "version": roadmap.meta.version,
            "title": f"Тест блока · {roadmap.meta.title}",
            "entry_step_id": test_step_id,
            "intro_step_id": None,
        },
        "steps": [
            {
                "id": test_step_id,
                "title": f"Тест блока из {step.title}",
                "notes": "Временный этап, созданный Roadmap Studio.",
                "actions": [action.model_dump(mode="json")],
            }
        ],
    }
    return Roadmap.model_validate(test_data), test_step_id
