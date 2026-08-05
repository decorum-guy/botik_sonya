from __future__ import annotations

import html
import sys
from pathlib import Path
from typing import Any

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import FSInputFile, Message

from app.memory_debug import MemoryDebugMiddleware, memory_debug


DEBUG_COMMANDS = {
    "/memory_debug_on",
    "/memory_debug_off",
    "/memory_debug_status",
}


def _state_module() -> Any:
    import app.main as bot_app

    return bot_app


def _command_name(message: Message) -> str:
    command = (message.text or "").strip().split(maxsplit=1)[0]
    return command.split("@", 1)[0].lower()


def _is_debug_command(message: Message) -> bool:
    return _command_name(message) in DEBUG_COMMANDS


def _protect_debug_commands_from_builder_filters() -> None:
    for module in tuple(sys.modules.values()):
        spec_name = getattr(getattr(module, "__spec__", None), "name", None)
        module_name = getattr(module, "__name__", None)
        if spec_name != "tools.builder_server" and module_name != "tools.builder_server":
            continue

        for class_name in ("ActiveTestInputFilter", "EditorMemoryMessageFilter"):
            filter_class = getattr(module, class_name, None)
            if filter_class is None or getattr(filter_class, "_memory_debug_guard", False):
                continue
            original_call = filter_class.__call__

            async def guarded_call(self, message, _original_call=original_call):
                if _is_debug_command(message):
                    return False
                return await _original_call(self, message)

            filter_class.__call__ = guarded_call
            filter_class._memory_debug_guard = True


async def _require_admin(message: Message) -> bool:
    state = _state_module()
    admin_access = getattr(state, "admin_access", None)
    if (
        message.from_user is not None
        and admin_access is not None
        and await admin_access.is_admin(message.from_user.id)
    ):
        return True
    await message.answer(
        "Команда недоступна. Сначала авторизуйся через /admin <пароль>."
    )
    return False


async def memory_debug_on(message: Message) -> None:
    if not await _require_admin(message) or message.from_user is None:
        return

    state = _state_module()
    storage = getattr(state, "storage", None)
    if storage is None:
        await message.answer("Хранилище ещё не инициализировано.")
        return

    directory = Path(storage.path).parent / "debug"
    previous = await memory_debug.status(message.from_user.id)
    session = await memory_debug.start(message.from_user.id, directory)
    if previous is not None:
        await message.answer(
            "🟡 Дебаг уже включён.\n"
            f"Лог: <code>{html.escape(str(session.path))}</code>\n"
            f"Событий записано: <b>{session.events}</b>."
        )
        return

    await message.answer(
        "🔴 <b>Дебаг сохранения воспоминаний включён</b>\n\n"
        "Теперь начни или перезапиши воспоминание и перешли всю пачку сообщений. "
        "Лог фиксирует каждый входящий update, message_id, тип контента, медиагруппу, "
        "результат записи и исключения.\n\n"
        "Когда закончишь и подождёшь несколько секунд, отправь /memory_debug_off — "
        "бот пришлёт JSONL-файл."
    )


async def memory_debug_status(message: Message) -> None:
    if not await _require_admin(message) or message.from_user is None:
        return
    session = await memory_debug.status(message.from_user.id)
    if session is None:
        await message.answer("⚪️ Дебаг выключен. Запуск: /memory_debug_on")
        return
    await message.answer(
        "🔴 Дебаг включён.\n"
        f"Начат: <code>{html.escape(session.started_at)}</code>\n"
        f"Событий: <b>{session.events}</b>\n"
        f"Уникальных входящих сообщений: <b>{len(session.seen_incoming)}</b>"
    )


async def memory_debug_off(message: Message) -> None:
    if not await _require_admin(message) or message.from_user is None:
        return

    session = await memory_debug.stop(message.from_user.id)
    if session is None:
        await message.answer("⚪️ Дебаг уже выключен. Запуск: /memory_debug_on")
        return

    state = _state_module()
    storage = getattr(state, "storage", None)
    memory_note = ""
    if storage is not None:
        active = await storage.admin_session(message.from_user.id)
        if active and active[0] in {"memory_record", "memory_editor"}:
            count = await storage.memory_message_count(active[1])
            memory_note = f"\nАктивное воспоминание: {active[1]} · сохранено {count}."

    await message.answer_document(
        FSInputFile(session.path),
        caption=(
            "🧾 Дебаг-лог готов. "
            f"Событий: {session.events}; входящих сообщений: "
            f"{len(session.seen_incoming)}.{memory_note}"
        ),
    )


def install_memory_debug(router: Router) -> None:
    if getattr(router, "_memory_debug_installed", False):
        return

    _protect_debug_commands_from_builder_filters()
    router.message.outer_middleware(MemoryDebugMiddleware())

    for handler, command in (
        (memory_debug_on, "memory_debug_on"),
        (memory_debug_status, "memory_debug_status"),
        (memory_debug_off, "memory_debug_off"),
    ):
        router.message.register(handler, Command(command))
        registered = router.message.handlers.pop()
        router.message.handlers.insert(0, registered)

    router._memory_debug_installed = True
