from __future__ import annotations

import html
import logging
from dataclasses import dataclass
from typing import Any

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message, ReplyParameters

from app.media_retry import retry_transient_telegram
from app.models import MemoryAction, Roadmap

logger = logging.getLogger(__name__)

BATCH_FORWARD_LIMIT = 100


@dataclass(frozen=True, slots=True)
class BatchPreviewResult:
    stored_count: int
    forwarded_count: int
    batch_count: int


def _state_module() -> Any:
    import app.main as bot_app

    return bot_app


def _memory_action(roadmap: Roadmap, memory_id: str) -> MemoryAction | None:
    for step in roadmap.steps:
        for action in step.actions:
            if isinstance(action, MemoryAction) and action.memory_id == memory_id:
                return action
    return None


def _header_text(action: MemoryAction | None, memory_id: str) -> str:
    if action is None:
        return (
            "🧪 <b>ПАКЕТНЫЙ ТЕСТ ВОСПОМИНАНИЯ</b>\n\n"
            f"ID: <code>{html.escape(memory_id)}</code>\n"
            "━━━━━━━━━━━━━━━━━━━━"
        )
    return (
        f"🧪 <b>ПАКЕТНЫЙ ТЕСТ</b>\n"
        f"<b>{html.escape(action.title)} {action.number}/{action.total}</b>\n\n"
        f"{html.escape(action.date_text)}\n"
        "━━━━━━━━━━━━━━━━━━━━"
    )


def _source_batches(
    messages: list[tuple[int, int, int, str, str | None]],
) -> list[tuple[int, list[int]]]:
    """Create ordered forwardMessages calls without crossing source chats.

    In normal use every saved fragment comes from the same private admin-bot chat.
    Keeping this grouping makes the test safe for legacy databases too. Telegram
    accepts at most 100 message IDs per forwardMessages request.
    """

    batches: list[tuple[int, list[int]]] = []
    current_chat_id: int | None = None
    current_ids: list[int] = []

    for _, source_chat_id, source_message_id, _, _ in messages:
        if (
            current_ids
            and (
                source_chat_id != current_chat_id
                or len(current_ids) >= BATCH_FORWARD_LIMIT
            )
        ):
            batches.append((int(current_chat_id), current_ids))
            current_ids = []

        current_chat_id = source_chat_id
        current_ids.append(source_message_id)

    if current_ids and current_chat_id is not None:
        batches.append((current_chat_id, current_ids))
    return batches


async def _send_text(bot, chat_id: int, text: str, **kwargs):
    return await retry_transient_telegram(
        lambda: bot.send_message(chat_id, text, **kwargs),
        chat_id=chat_id,
        label="memory batch test text",
    )


async def send_memory_batch_preview(
    *,
    bot,
    storage,
    roadmap: Roadmap,
    destination_chat_id: int,
    memory_id: str,
) -> BatchPreviewResult:
    """Replay one memory through forwardMessages without inter-message pauses."""

    action = _memory_action(roadmap, memory_id)
    header_message = await _send_text(
        bot,
        destination_chat_id,
        _header_text(action, memory_id),
    )

    if action is not None and action.intro:
        await _send_text(bot, destination_chat_id, action.intro)

    messages = await storage.memory_messages(memory_id)
    forwarded_count = 0
    batches = _source_batches(messages)

    for source_chat_id, message_ids in batches:
        sent_ids = await retry_transient_telegram(
            lambda source_chat_id=source_chat_id, message_ids=message_ids: bot.forward_messages(
                chat_id=destination_chat_id,
                from_chat_id=source_chat_id,
                message_ids=message_ids,
            ),
            chat_id=destination_chat_id,
            label=(
                f"memory batch forward {memory_id} "
                f"#{message_ids[0]}..#{message_ids[-1]}"
            ),
        )
        forwarded_count += len(sent_ids)

    if not messages:
        await _send_text(
            bot,
            destination_chat_id,
            f"[Тест] Воспоминание {html.escape(memory_id)} пока пустое.",
        )

    if action is not None and action.outro:
        await _send_text(bot, destination_chat_id, action.outro)

    if forwarded_count == len(messages):
        status = f"Отправлено: <b>{forwarded_count}</b> сообщений."
    else:
        status = (
            f"Telegram переслал <b>{forwarded_count}</b> из "
            f"<b>{len(messages)}</b> сообщений. Часть элементов была пропущена."
        )

    await _send_text(
        bot,
        destination_chat_id,
        "↩️ <b>Воспоминание восстановлено</b>\n"
        f"{status}\n"
        "Нажми на это сообщение-ответ, чтобы сразу вернуться к началу воспоминания.",
        reply_parameters=ReplyParameters(
            message_id=header_message.message_id,
            allow_sending_without_reply=True,
        ),
    )

    logger.info(
        "Batch memory preview %s: stored=%s forwarded=%s batches=%s",
        memory_id,
        len(messages),
        forwarded_count,
        len(batches),
    )
    return BatchPreviewResult(
        stored_count=len(messages),
        forwarded_count=forwarded_count,
        batch_count=len(batches),
    )


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


async def memory_preview_batch(message: Message, command: CommandObject) -> None:
    if not await _require_admin(message):
        return

    memory_id = (command.args or "").strip()
    if not memory_id:
        await message.answer("Формат: /memory_preview_batch first_meeting")
        return

    state = _state_module()
    engine = getattr(state, "engine", None)
    storage = getattr(state, "storage", None)
    if engine is None or storage is None:
        await message.answer("Движок или база ещё не инициализированы.")
        return

    await send_memory_batch_preview(
        bot=message.bot,
        storage=storage,
        roadmap=engine.roadmap,
        destination_chat_id=message.chat.id,
        memory_id=memory_id,
    )


def install_memory_batch_preview(router: Router) -> None:
    if getattr(router, "_memory_batch_preview_installed", False):
        return

    router.message.register(memory_preview_batch, Command("memory_preview_batch"))
    registered = router.message.handlers.pop()
    router.message.handlers.insert(0, registered)
    router._memory_batch_preview_installed = True
