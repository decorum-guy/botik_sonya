from __future__ import annotations

import asyncio
import html
import logging
import sys
from collections.abc import Iterable
from typing import Any

from aiogram import Router
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import Command, CommandObject
from aiogram.types import Message, ReplyParameters

from app.media_retry import retry_transient_telegram
from app.models import MemoryAction

logger = logging.getLogger(__name__)

MEMORY_MODE_STREAM = "stream"
MEMORY_MODE_BATCH = "batch"
VALID_MEMORY_MODES = frozenset({MEMORY_MODE_STREAM, MEMORY_MODE_BATCH})
MEMORY_MODE_SETTING_PREFIX = "memory_mode:"
BATCH_FORWARD_LIMIT = 100

_MODE_ALIASES = {
    "stream": MEMORY_MODE_STREAM,
    "streaming": MEMORY_MODE_STREAM,
    "flow": MEMORY_MODE_STREAM,
    "поток": MEMORY_MODE_STREAM,
    "потоковый": MEMORY_MODE_STREAM,
    "обычный": MEMORY_MODE_STREAM,
    "batch": MEMORY_MODE_BATCH,
    "батч": MEMORY_MODE_BATCH,
    "батчевый": MEMORY_MODE_BATCH,
    "пакет": MEMORY_MODE_BATCH,
    "пакетный": MEMORY_MODE_BATCH,
}

_PROTECTED_COMMANDS = {"/memory_mode", "/memory_list"}


def memory_mode_setting_key(memory_id: str) -> str:
    return f"{MEMORY_MODE_SETTING_PREFIX}{memory_id}"


async def get_memory_mode(storage: Any, memory_id: str) -> str:
    """Return the saved playback mode, defaulting legacy memories to stream."""

    getter = getattr(storage, "get_setting", None)
    if getter is None:
        return MEMORY_MODE_STREAM
    value = await getter(memory_mode_setting_key(memory_id))
    return value if value in VALID_MEMORY_MODES else MEMORY_MODE_STREAM


async def set_memory_mode(storage: Any, memory_id: str, mode: str) -> None:
    if mode not in VALID_MEMORY_MODES:
        raise ValueError(f"Unsupported memory mode: {mode}")
    await storage.set_setting(memory_mode_setting_key(memory_id), mode)


def memory_mode_label(mode: str) -> str:
    if mode == MEMORY_MODE_BATCH:
        return "📦 batch · одной пачкой, сохраняет reply-связи"
    return "⏳ stream · по одному сообщению с паузами 1–3,5 с"


def _memory_action(roadmap: Any, memory_id: str) -> MemoryAction | None:
    for step in getattr(roadmap, "steps", []):
        for action in getattr(step, "actions", []):
            if isinstance(action, MemoryAction) and action.memory_id == memory_id:
                return action
    return None


def _header_text(action: MemoryAction | None, memory_id: str) -> str:
    if action is None:
        return (
            "<b>ВОССТАНОВЛЕНИЕ ВОСПОМИНАНИЯ</b>\n\n"
            f"<code>{html.escape(memory_id)}</code>\n"
            "━━━━━━━━━━━━━━━━━━━━"
        )
    return (
        f"<b>{html.escape(action.title)} {action.number}/{action.total}</b>\n\n"
        f"{html.escape(action.date_text)}\n"
        "━━━━━━━━━━━━━━━━━━━━"
    )


def _source_batches(
    messages: Iterable[tuple[int, int, int, str, str | None]],
) -> list[tuple[int, list[int]]]:
    """Build forwardMessages calls without mixing source chats or exceeding 100 IDs."""

    batches: list[tuple[int, list[int]]] = []
    current_chat_id: int | None = None
    current_ids: list[int] = []

    for _, source_chat_id, source_message_id, _, _ in messages:
        if current_ids and (
            source_chat_id != current_chat_id
            or len(current_ids) >= BATCH_FORWARD_LIMIT
        ):
            batches.append((int(current_chat_id), current_ids))
            current_ids = []

        current_chat_id = source_chat_id
        current_ids.append(source_message_id)

    if current_ids and current_chat_id is not None:
        batches.append((current_chat_id, current_ids))
    return batches


async def _send_memory_text(self, chat_id: int, text: str, **kwargs: Any):
    return await retry_transient_telegram(
        lambda: self.bot.send_message(chat_id, text, **kwargs),
        chat_id=chat_id,
        label="memory text",
    )


async def _deliver_memory_batch(
    self,
    chat_id: int,
    memory_id: str,
    messages: list[tuple[int, int, int, str, str | None]],
) -> tuple[int, str | None]:
    """Deliver through forwardMessages and keep the quest moving on permanent errors."""

    delivered_count = 0
    notes: list[str] = []

    for source_chat_id, message_ids in _source_batches(messages):
        try:
            sent = await retry_transient_telegram(
                lambda source_chat_id=source_chat_id, message_ids=message_ids: (
                    self.bot.forward_messages(
                        chat_id=chat_id,
                        from_chat_id=source_chat_id,
                        message_ids=message_ids,
                    )
                ),
                chat_id=chat_id,
                label=(
                    f"memory batch {memory_id} "
                    f"#{message_ids[0]}..#{message_ids[-1]}"
                ),
            )
        except (TelegramBadRequest, TelegramForbiddenError) as exc:
            logger.warning(
                "Batch forwarding failed for memory %s (%s); falling back to "
                "individual delivery without pauses",
                memory_id,
                exc,
            )
            for source_message_id in message_ids:
                await self._deliver_memory_message(
                    chat_id,
                    source_chat_id,
                    source_message_id,
                )
                delivered_count += 1
            notes.append(
                "часть переписки пришлось отправить по одному; "
                "reply-связи в этом фрагменте могли потеряться"
            )
            continue

        sent_count = len(sent)
        delivered_count += sent_count
        if sent_count != len(message_ids):
            notes.append("Telegram пропустил часть недоступных элементов")
            logger.error(
                "Telegram skipped messages in batch memory %s: requested=%s sent=%s "
                "source_chat_id=%s range=%s..%s",
                memory_id,
                len(message_ids),
                sent_count,
                source_chat_id,
                message_ids[0],
                message_ids[-1],
            )

    note = "; ".join(dict.fromkeys(notes)) or None
    return delivered_count, note


async def _play_memory_content(
    self,
    chat_id: int,
    memory_id: str,
    action: MemoryAction | None,
    *,
    mode_override: str | None = None,
) -> int:
    header_message = await self._send_memory_text(
        chat_id,
        _header_text(action, memory_id),
    )

    if action is not None and action.intro:
        await self._send_memory_text(chat_id, action.intro)

    messages = await self.storage.memory_messages(memory_id)
    mode = mode_override or await get_memory_mode(self.storage, memory_id)
    delivery_note: str | None = None
    delivered_count = 0

    if not messages:
        await self._send_memory_text(
            chat_id,
            f"[Тест] Воспоминание {html.escape(memory_id)} пока пустое.",
        )
    elif mode == MEMORY_MODE_BATCH:
        delivered_count, delivery_note = await _deliver_memory_batch(
            self,
            chat_id,
            memory_id,
            messages,
        )
    else:
        for index, (_, source_chat_id, source_message_id, _, _) in enumerate(messages):
            await self._deliver_memory_message(
                chat_id,
                source_chat_id,
                source_message_id,
            )
            delivered_count += 1
            if index < len(messages) - 1:
                await asyncio.sleep(self._memory_message_delay_seconds())

    if action is not None and action.outro:
        await self._send_memory_text(chat_id, action.outro)

    warning = f"\n⚠️ {html.escape(delivery_note)}." if delivery_note else ""
    await self._send_memory_text(
        chat_id,
        "↩️ <b>Воспоминание завершено</b>\n"
        "Нажми на сообщение, на которое дан этот ответ, чтобы вернуться к началу."
        f"{warning}",
        reply_parameters=ReplyParameters(
            message_id=header_message.message_id,
            allow_sending_without_reply=True,
        ),
    )

    logger.info(
        "Memory %s delivered to chat %s in %s mode: stored=%s delivered=%s note=%s",
        memory_id,
        chat_id,
        mode,
        len(messages),
        delivered_count,
        delivery_note,
    )
    return len(messages)


async def _play_memory(self, chat_id: int, action: MemoryAction) -> int:
    return await _play_memory_content(
        self,
        chat_id,
        action.memory_id,
        action,
    )


async def _preview_memory(
    self,
    destination_chat_id: int,
    memory_id: str,
    *,
    mode_override: str | None = None,
) -> int:
    action = _memory_action(self.roadmap, memory_id)
    return await _play_memory_content(
        self,
        destination_chat_id,
        memory_id,
        action,
        mode_override=mode_override,
    )


def install_memory_modes(engine_module: Any) -> None:
    """Install persistent stream/batch memory playback on QuestEngine."""

    engine_class = engine_module.QuestEngine
    if getattr(engine_class, "_memory_modes_installed", False):
        return

    # Keep the delay generator replaceable in tests while preserving the existing
    # public helper in app.engine.
    engine_class._memory_message_delay_seconds = staticmethod(
        engine_module.memory_message_delay_seconds
    )
    engine_class._send_memory_text = _send_memory_text
    engine_class.play_memory = _play_memory
    engine_class.preview_memory = _preview_memory
    engine_class._memory_modes_installed = True


def _state_module() -> Any:
    import app.main as bot_app

    return bot_app


def _command_name(message: Message) -> str:
    command = (message.text or "").strip().split(maxsplit=1)[0]
    return command.split("@", 1)[0].lower()


def _protect_memory_commands_from_builder_filters() -> None:
    """Keep memory admin commands from becoming Studio test input or content."""

    for module in tuple(sys.modules.values()):
        spec_name = getattr(getattr(module, "__spec__", None), "name", None)
        module_name = getattr(module, "__name__", None)
        if spec_name != "tools.builder_server" and module_name != "tools.builder_server":
            continue

        for class_name in ("ActiveTestInputFilter", "EditorMemoryMessageFilter"):
            filter_class = getattr(module, class_name, None)
            if filter_class is None or getattr(filter_class, "_memory_mode_guard", False):
                continue
            original_call = filter_class.__call__

            async def guarded_call(self, message, _original_call=original_call):
                if _command_name(message) in _PROTECTED_COMMANDS:
                    return False
                return await _original_call(self, message)

            filter_class.__call__ = guarded_call
            filter_class._memory_mode_guard = True


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


async def _known_memory_ids(state: Any) -> list[str]:
    ids: list[str] = []
    seen: set[str] = set()

    for item in getattr(state, "memory_variables", []):
        memory_id = str(getattr(item, "id", "")).strip()
        if memory_id and memory_id not in seen:
            seen.add(memory_id)
            ids.append(memory_id)

    storage = getattr(state, "storage", None)
    if storage is not None:
        for memory_id, _ in await storage.list_memories():
            if memory_id not in seen:
                seen.add(memory_id)
                ids.append(memory_id)
    return ids


async def memory_mode_command(message: Message, command: CommandObject) -> None:
    if not await _require_admin(message):
        return

    state = _state_module()
    storage = getattr(state, "storage", None)
    if storage is None:
        await message.answer("База ещё не инициализирована.")
        return

    args = (command.args or "").split()
    known_ids = await _known_memory_ids(state)

    if not args:
        if not known_ids:
            await message.answer(
                "Пока нет воспоминаний. Формат после создания: "
                "<code>/memory_mode ID batch</code>."
            )
            return
        lines = []
        for memory_id in known_ids:
            mode = await get_memory_mode(storage, memory_id)
            lines.append(
                f"• <code>{html.escape(memory_id)}</code> — {memory_mode_label(mode)}"
            )
        await message.answer(
            "<b>Режимы воспоминаний</b>\n\n"
            + "\n".join(lines)
            + "\n\nИзменить:\n"
            "<code>/memory_mode ID batch</code> — одной пачкой, для reply\n"
            "<code>/memory_mode ID stream</code> — с паузами"
        )
        return

    memory_id = args[0]
    if memory_id not in known_ids:
        await message.answer(
            f"Воспоминание <code>{html.escape(memory_id)}</code> не найдено. "
            "Список: /memory_list"
        )
        return

    if len(args) == 1:
        mode = await get_memory_mode(storage, memory_id)
        await message.answer(
            f"<code>{html.escape(memory_id)}</code> сейчас: {memory_mode_label(mode)}\n\n"
            f"Изменить: <code>/memory_mode {html.escape(memory_id)} batch</code> "
            "или <code>stream</code>."
        )
        return

    requested = args[1].lower()
    mode = _MODE_ALIASES.get(requested)
    if mode is None:
        await message.answer(
            "Неизвестный режим. Используй <code>batch</code> или <code>stream</code>."
        )
        return

    await set_memory_mode(storage, memory_id, mode)
    await message.answer(
        f"✅ Для <code>{html.escape(memory_id)}</code> установлен режим:\n"
        f"{memory_mode_label(mode)}"
    )


async def memory_list_command(message: Message) -> None:
    if not await _require_admin(message):
        return

    state = _state_module()
    storage = getattr(state, "storage", None)
    if storage is None:
        await message.answer("База ещё не инициализирована.")
        return

    items = await storage.list_memories()
    if not items:
        await message.answer("Пока пусто.")
        return

    lines = []
    for memory_id, count in items:
        mode = await get_memory_mode(storage, memory_id)
        lines.append(
            f"• <code>{html.escape(memory_id)}</code> — {count} сообщений · "
            f"{memory_mode_label(mode)}"
        )
    await message.answer("<b>Сохранённые воспоминания</b>\n\n" + "\n".join(lines))


def install_memory_mode_commands(router: Router) -> None:
    if getattr(router, "_memory_mode_commands_installed", False):
        return

    _protect_memory_commands_from_builder_filters()
    for handler, command in (
        (memory_mode_command, "memory_mode"),
        (memory_list_command, "memory_list"),
    ):
        router.message.register(handler, Command(command))
        registered = router.message.handlers.pop()
        router.message.handlers.insert(0, registered)
    router._memory_mode_commands_installed = True
