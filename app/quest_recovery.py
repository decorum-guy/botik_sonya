from __future__ import annotations

import asyncio
import html
import inspect
import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Awaitable, Callable, Literal

logger = logging.getLogger(__name__)

FAILURE_SETTING_PREFIX = "quest_failure:"
EXECUTION_OK = "ok"
EXECUTION_FAILED = "failed"
EXECUTION_BUSY = "busy"

AdminIdGetter = Callable[[], int | None | Awaitable[int | None]]
ContinueStatus = Literal[
    "completed",
    "resumed",
    "failed",
    "busy",
    "waiting",
    "missing",
]


@dataclass(frozen=True, slots=True)
class ContinueQuestResult:
    status: ContinueStatus
    message: str


def _failure_key(chat_id: int) -> str:
    return f"{FAILURE_SETTING_PREFIX}{chat_id}"


def _recovery_enabled(engine: Any) -> bool:
    return bool(getattr(engine, "_quest_recovery_enabled", False))


def _execution_lock(engine: Any, chat_id: int) -> asyncio.Lock:
    locks: dict[int, asyncio.Lock] = getattr(engine, "_quest_recovery_locks", {})
    engine._quest_recovery_locks = locks
    return locks.setdefault(chat_id, asyncio.Lock())


async def _read_failure(engine: Any, chat_id: int) -> dict[str, Any] | None:
    getter = getattr(engine.storage, "get_setting", None)
    if not callable(getter):
        return None
    raw = await getter(_failure_key(chat_id))
    if not raw:
        return None
    try:
        payload = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        logger.error("Invalid persisted quest failure for chat %s: %r", chat_id, raw)
        return None
    return payload if isinstance(payload, dict) else None


async def _clear_failure(engine: Any, chat_id: int) -> None:
    getter = getattr(engine.storage, "get_setting", None)
    setter = getattr(engine.storage, "set_setting", None)
    if not callable(getter) or not callable(setter):
        return
    if await getter(_failure_key(chat_id)):
        await setter(_failure_key(chat_id), "")


async def _admin_id(engine: Any) -> int | None:
    getter: AdminIdGetter | None = getattr(
        engine,
        "_quest_recovery_admin_id_getter",
        None,
    )
    if getter is None:
        return None
    value = getter()
    if inspect.isawaitable(value):
        value = await value
    return int(value) if value is not None else None


async def _notify_admin(engine: Any, payload: dict[str, Any]) -> None:
    try:
        admin_id = await _admin_id(engine)
    except Exception:
        logger.exception("Could not resolve admin for quest recovery notification")
        return
    if admin_id is None:
        return

    step_id = html.escape(str(payload.get("step_id") or "неизвестно"))
    action_index = payload.get("action_index")
    action_number = "?" if action_index is None else str(int(action_index) + 1)
    action_type = html.escape(str(payload.get("action_type") or "неизвестно"))
    error_type = html.escape(str(payload.get("exception_type") or "Exception"))
    error_message = html.escape(str(payload.get("exception_message") or "без описания"))

    text = (
        "🚨 <b>Квест поставлен на аварийную паузу</b>\n\n"
        f"Этап: <code>{step_id}</code>\n"
        f"Блок: <code>{action_number}</code> · <code>{action_type}</code>\n"
        f"Ошибка: <code>{error_type}</code> — {error_message}\n\n"
        "Успешно завершённые блоки сохранены в SQLite. После устранения причины "
        "отправь <code>/continue</code>."
    )
    try:
        await engine.bot.send_message(admin_id, text, parse_mode="HTML")
    except Exception:
        logger.exception("Could not send quest recovery notification to admin %s", admin_id)


async def _record_failure(
    engine: Any,
    chat_id: int,
    source: str,
    exc: Exception,
) -> dict[str, Any]:
    logger.exception(
        "Unexpected quest failure in chat %s while handling %s",
        chat_id,
        source,
    )

    progress = None
    try:
        progress = await engine.storage.get_progress(chat_id)
    except Exception:
        logger.exception("Could not read quest progress after failure in chat %s", chat_id)

    action_type: str | None = None
    if progress is not None:
        try:
            step = engine.roadmap.step(progress.step_id)
            if 0 <= progress.action_index < len(step.actions):
                action_type = step.actions[progress.action_index].type
            elif progress.action_index == len(step.actions):
                action_type = "step_complete"
        except Exception:
            logger.exception("Could not inspect failed quest action in chat %s", chat_id)

    error_message = str(exc).strip() or repr(exc)
    payload: dict[str, Any] = {
        "chat_id": chat_id,
        "source": source,
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "step_id": progress.step_id if progress is not None else None,
        "action_index": progress.action_index if progress is not None else None,
        "action_type": action_type,
        "waiting": progress.waiting if progress is not None else None,
        "exception_type": type(exc).__name__,
        "exception_message": error_message[:1000],
    }

    setter = getattr(engine.storage, "set_setting", None)
    if callable(setter):
        try:
            await setter(
                _failure_key(chat_id),
                json.dumps(payload, ensure_ascii=False),
            )
        except Exception:
            logger.exception("Could not persist quest failure for chat %s", chat_id)

    await _notify_admin(engine, payload)
    return payload


async def _continue_quest(engine: Any, chat_id: int) -> ContinueQuestResult:
    progress = await engine.storage.get_progress(chat_id)
    if progress is None:
        return ContinueQuestResult(
            "missing",
            "Активного или остановленного квеста нет.",
        )

    failure = await _read_failure(engine, chat_id)
    if progress.waiting and failure is None:
        waiting_kind = str(progress.waiting.get("kind") or "unknown")
        labels = {
            "input": "ответ участницы",
            "buttons": "нажатие сюжетной кнопки",
            "memory_ack": "кнопку «Прочитала»",
        }
        return ContinueQuestResult(
            "waiting",
            "Квест не упал: сейчас он ожидает "
            f"{labels.get(waiting_kind, waiting_kind)}. Продолжать принудительно не нужно.",
        )

    lock = _execution_lock(engine, chat_id)
    if lock.locked():
        return ContinueQuestResult(
            "busy",
            "Квест уже выполняется. Вторая копия запуска не создана.",
        )

    outcome = await engine._execute(chat_id)
    if outcome == EXECUTION_BUSY:
        return ContinueQuestResult(
            "busy",
            "Квест уже выполняется. Вторая копия запуска не создана.",
        )
    if outcome == EXECUTION_FAILED:
        return ContinueQuestResult(
            "failed",
            "Повторный запуск снова остановился на ошибке. Точка сохранена, подробности отправлены админу.",
        )

    current = await engine.storage.get_progress(chat_id)
    if current is None:
        return ContinueQuestResult(
            "completed",
            "Квест продолжен и дошёл до завершения.",
        )
    return ContinueQuestResult(
        "resumed",
        "Квест продолжен с сохранённой точки и дошёл до следующего ожидания.",
    )


def _configure_recovery(engine: Any, admin_id_getter: AdminIdGetter) -> None:
    engine._quest_recovery_admin_id_getter = admin_id_getter
    engine._quest_recovery_enabled = True


def install_quest_recovery(engine_module: Any) -> None:
    """Persist unexpected quest failures and allow an admin-controlled resume."""

    engine_class = engine_module.QuestEngine
    if getattr(engine_class, "_quest_recovery_installed", False):
        return

    original_execute = engine_class._execute
    original_start = engine_class.start
    original_handle_answer = engine_class.handle_answer
    original_handle_button = engine_class.handle_button

    async def execute_with_recovery(self, chat_id: int):
        if not _recovery_enabled(self):
            return await original_execute(self, chat_id)

        lock = _execution_lock(self, chat_id)
        if lock.locked():
            logger.warning(
                "Ignored concurrent quest execution request for chat %s",
                chat_id,
            )
            return EXECUTION_BUSY

        async with lock:
            try:
                await original_execute(self, chat_id)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - this is the final safety net
                await _record_failure(self, chat_id, "execution", exc)
                return EXECUTION_FAILED
            await _clear_failure(self, chat_id)
            return EXECUTION_OK

    async def start_with_recovery(self, chat_id: int, step_id: str | None = None):
        if not _recovery_enabled(self):
            return await original_start(self, chat_id, step_id)
        try:
            return await original_start(self, chat_id, step_id)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - final guard before dispatcher
            await _record_failure(self, chat_id, "start", exc)
            return None

    async def answer_with_recovery(self, message):
        if not _recovery_enabled(self):
            return await original_handle_answer(self, message)
        try:
            return await original_handle_answer(self, message)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - final guard before dispatcher
            await _record_failure(self, message.chat.id, "answer", exc)
            return False

    async def button_with_recovery(self, chat_id: int, button_id: str):
        if not _recovery_enabled(self):
            return await original_handle_button(self, chat_id, button_id)
        try:
            return await original_handle_button(self, chat_id, button_id)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - final guard before dispatcher
            await _record_failure(self, chat_id, "button", exc)
            return False, "История временно остановлена. Администратор уже уведомлён."

    engine_class.configure_quest_recovery = _configure_recovery
    engine_class.quest_failure = _read_failure
    engine_class.continue_quest = _continue_quest
    engine_class._execute = execute_with_recovery
    engine_class.start = start_with_recovery
    engine_class.handle_answer = answer_with_recovery
    engine_class.handle_button = button_with_recovery
    engine_class._quest_recovery_installed = True
