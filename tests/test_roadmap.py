from __future__ import annotations

import os
import re
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from app.media_group import is_media_group_path, parse_media_group_path
from app.models import (
    AskInputAction,
    ButtonsAction,
    DelayAction,
    GotoAction,
    MediaAction,
    MemoryAction,
    SendTextAction,
    ValidatorSpec,
)
from app.roadmap import load_roadmap
from app.validation import validate_answer

ROOT = Path(__file__).resolve().parents[1]
ROADMAP_PATH = ROOT / "roadmap" / "quest.json"
State = tuple[str, int]


@dataclass
class FakeTelegram:
    """Record what the quest would send without contacting Telegram."""

    events: list[tuple[str, str, int]] = field(default_factory=list)

    def dispatch(self, step_id: str, action_index: int, action: object) -> None:
        if isinstance(action, SendTextAction):
            event = "text"
        elif isinstance(action, MediaAction):
            event = action.type.removeprefix("send_")
        elif isinstance(action, DelayAction):
            event = "delay"
        elif isinstance(action, MemoryAction):
            event = "memory"
        elif isinstance(action, AskInputAction):
            event = "input"
        elif isinstance(action, ButtonsAction):
            event = "buttons"
        elif isinstance(action, GotoAction):
            event = "goto"
        else:  # pragma: no cover - the Pydantic action union should prevent this
            raise AssertionError(f"Unsupported action in {step_id}: {action!r}")
        self.events.append((event, step_id, action_index))


def _valid_answer(spec: ValidatorSpec) -> str | None:
    if spec.type == "any":
        return "готово"
    if spec.type in {"text_exact", "text_contains"}:
        return spec.values[0]
    if spec.type == "integer_equal":
        return str(spec.number)
    if spec.type == "integer_range":
        return str(spec.minimum)
    if spec.type == "date_equal":
        return datetime.strptime(spec.date, "%Y-%m-%d").strftime("%d.%m.%Y")
    if spec.type == "regex":
        flags = 0 if spec.case_sensitive else re.IGNORECASE
        re.compile(spec.pattern, flags=flags)
        return None
    raise AssertionError(f"Unknown validator type: {spec.type}")


def _check_validator(action: AskInputAction, location: str) -> None:
    answer = _valid_answer(action.validator)
    if answer is None:
        return
    assert validate_answer(answer, action.validator), (
        f"Validator at {location} rejects its own valid test answer {answer!r}"
    )


def _media_paths(action: MediaAction) -> list[str]:
    if not is_media_group_path(action.path):
        return [action.path]
    return [item.path for item in parse_media_group_path(action.path)]


def _next_states(step_id: str, action_index: int, action: object) -> list[State]:
    next_in_step = (step_id, action_index + 1)
    if isinstance(action, AskInputAction):
        return [(action.next_step, 0)] if action.next_step else [next_in_step]
    if isinstance(action, ButtonsAction):
        return [
            (button.next_step, 0) if button.next_step else next_in_step
            for button in action.buttons
        ]
    if isinstance(action, GotoAction):
        return [(action.step_id, 0)]
    return [next_in_step]


def test_production_roadmap_dry_run() -> None:
    """Exhaustively dry-run every reachable action and every button branch."""

    roadmap = load_roadmap(ROADMAP_PATH)
    assert roadmap.steps, "ROADMAP has no steps"
    assert roadmap.meta.entry_step_id, "ROADMAP has no entry step"

    step_ids = {step.id for step in roadmap.steps}
    assert len(step_ids) == len(roadmap.steps), "ROADMAP contains duplicate step IDs"
    assert all(step.actions for step in roadmap.steps), "ROADMAP contains an empty step"

    fake_telegram = FakeTelegram()
    queue: deque[State] = deque([(roadmap.meta.entry_step_id, 0)])
    if (
        roadmap.meta.intro_step_id
        and roadmap.meta.intro_step_id != roadmap.meta.entry_step_id
    ):
        queue.append((roadmap.meta.intro_step_id, 0))

    visited_actions: set[State] = set()
    visited_states: set[State] = set()
    terminal_steps: set[str] = set()
    media_paths: set[str] = set()
    memory_actions: list[MemoryAction] = []

    while queue:
        step_id, action_index = queue.popleft()
        state = (step_id, action_index)
        if state in visited_states:
            continue
        visited_states.add(state)

        step = roadmap.step(step_id)
        assert action_index <= len(step.actions), (
            f"Execution escaped step {step_id}: action index {action_index}"
        )
        if action_index == len(step.actions):
            terminal_steps.add(step_id)
            continue

        action = step.actions[action_index]
        location = f"{step_id}[{action_index}]"
        visited_actions.add(state)
        fake_telegram.dispatch(step_id, action_index, action)

        if isinstance(action, SendTextAction):
            assert action.text.strip(), f"Empty text at {location}"
            if action.delivery_mode != "instant" and action.stream_segments:
                assert any(segment.text for segment in action.stream_segments), (
                    f"Streaming text at {location} has no visible segments"
                )
        elif isinstance(action, MediaAction):
            for media_path in _media_paths(action):
                assert media_path.startswith("media/"), (
                    f"Media at {location} must be inside media/: {media_path}"
                )
                assert not media_path.rstrip("/").endswith("/file"), (
                    f"Placeholder media path remains at {location}: {media_path}"
                )
                media_paths.add(media_path)
        elif isinstance(action, MemoryAction):
            assert action.memory_id.strip(), f"Empty memory ID at {location}"
            assert action.number <= action.total, (
                f"Memory number exceeds total at {location}: "
                f"{action.number}/{action.total}"
            )
            memory_actions.append(action)
        elif isinstance(action, AskInputAction):
            _check_validator(action, location)
        elif isinstance(action, ButtonsAction):
            button_ids = [button.id for button in action.buttons]
            assert len(button_ids) == len(set(button_ids)), (
                f"Duplicate button IDs inside {location}"
            )
            for button in action.buttons:
                callback_data = f"quest:{button.id}".encode()
                assert len(callback_data) <= 64, (
                    f"Telegram callback is longer than 64 bytes at {location}: "
                    f"{button.id!r}"
                )

        queue.extend(_next_states(step_id, action_index, action))

    all_actions = {
        (step.id, action_index)
        for step in roadmap.steps
        for action_index in range(len(step.actions))
    }
    unreachable = sorted(all_actions - visited_actions)
    assert not unreachable, (
        "ROADMAP contains actions that can never run: "
        + ", ".join(f"{step_id}[{index}]" for step_id, index in unreachable)
    )
    assert terminal_steps, "ROADMAP has no route that can finish"
    assert len(terminal_steps) == 1, (
        "ROADMAP has several unintended endings: " + ", ".join(sorted(terminal_steps))
    )
    assert len(fake_telegram.events) == len(all_actions), (
        "Dry-run did not simulate every action"
    )

    if memory_actions:
        totals = {action.total for action in memory_actions}
        assert len(totals) == 1, "Memory blocks use inconsistent total values"
        total = totals.pop()
        numbers = [action.number for action in memory_actions]
        assert len(numbers) == len(set(numbers)), "Memory numbers are duplicated"
        assert set(numbers) == set(range(1, total + 1)), (
            f"Memory numbering must cover 1..{total}, got {sorted(numbers)}"
        )
        memory_ids = [action.memory_id for action in memory_actions]
        assert len(memory_ids) == len(set(memory_ids)), "Memory IDs are duplicated"

    # Private media are intentionally absent from public GitHub CI. On the Mac
    # used for the real quest, pytest also verifies that every referenced file
    # is physically present before day X.
    if os.getenv("CI", "").lower() not in {"1", "true", "yes"}:
        missing_media = sorted(
            media_path
            for media_path in media_paths
            if not (ROOT / media_path).is_file()
        )
        assert not missing_media, (
            "ROADMAP references missing media files: " + ", ".join(missing_media)
        )
