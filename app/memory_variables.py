from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


@dataclass(frozen=True, slots=True)
class MemoryVariable:
    id: str
    label: str
    order: int
    usages: int


def _label_for(action: dict[str, Any], memory_id: str, order: int) -> str:
    for key in ("title", "date_text", "intro"):
        value = action.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip().splitlines()[0][:120]
    number = action.get("number")
    if number not in (None, ""):
        return f"Воспоминание {number}"
    return f"Воспоминание {order}: {memory_id}"


def collect_memory_variables_from_data(data: dict[str, Any]) -> list[MemoryVariable]:
    ordered: list[str] = []
    labels: dict[str, str] = {}
    usages: dict[str, int] = {}

    steps = data.get("steps", [])
    if not isinstance(steps, list):
        return []

    for step in steps:
        if not isinstance(step, dict):
            continue
        actions = step.get("actions", [])
        if not isinstance(actions, list):
            continue
        for action in actions:
            if not isinstance(action, dict) or action.get("type") != "memory_reconstruction":
                continue
            memory_id = str(action.get("memory_id", "")).strip()
            if not memory_id:
                continue
            if memory_id not in usages:
                ordered.append(memory_id)
                labels[memory_id] = _label_for(action, memory_id, len(ordered))
                usages[memory_id] = 0
            usages[memory_id] += 1

    return [
        MemoryVariable(
            id=memory_id,
            label=labels[memory_id],
            order=index,
            usages=usages[memory_id],
        )
        for index, memory_id in enumerate(ordered, start=1)
    ]


def collect_memory_variables(path: Path) -> list[MemoryVariable]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("ROADMAP root must be an object")
    return collect_memory_variables_from_data(data)


async def missing_memory_variables(
    storage: Any,
    variables: Iterable[MemoryVariable],
) -> list[MemoryVariable]:
    missing: list[MemoryVariable] = []
    for variable in variables:
        if not await storage.memory_messages(variable.id):
            missing.append(variable)
    return missing
