from __future__ import annotations

import asyncio
import html
import logging
import secrets
from typing import Any

from aiogram.types import InlineKeyboardMarkup, ReplyParameters

from app.button_styles import ButtonStyleAlias, callback_button
from app.memory_modes import (
    MEMORY_MODE_BATCH,
    _deliver_memory_batch,
    _header_text,
    get_memory_mode,
)
from app.models import (
    AskInputAction,
    ButtonsAction,
    DelayAction,
    GotoAction,
    MediaAction,
    MemoryAction,
    SendTextAction,
)

logger = logging.getLogger(__name__)

MEMORY_ACK_CALLBACK_PREFIX = "memory_ack:"
MEMORY_ACK_WAITING_KIND = "memory_ack"
MEMORY_FINISH_OLD_TITLE = "Воспоминание завершено"
MEMORY_FINISH_TITLE = "Воспоминание восстановлено"


def _ack_keyboard(token: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                callback_button(
                    text="Прочитала",
                    callback_data=f"quest:{MEMORY_ACK_CALLBACK_PREFIX}{token}",
                    style=ButtonStyleAlias.SUCCESS,
                )
            ]
        ]
    )


async def _play_memory_and_wait(
    self,
    chat_id: int,
    action: MemoryAction,
    *,
    step_id: str,
    action_index: int,
    next_index: int,
) -> int:
    """Deliver a memory, then persist a hard pause until its button is pressed."""

    header_message = await self._send_memory_text(
        chat_id,
        _header_text(action, action.memory_id),
    )

    if action.intro:
        await self._send_memory_text(chat_id, action.intro)

    messages = await self.storage.memory_messages(action.memory_id)
    mode = await get_memory_mode(self.storage, action.memory_id)
    delivery_note: str | None = None
    delivered_count = 0

    if not messages:
        await self._send_memory_text(
            chat_id,
            f"[Тест] Воспоминание {html.escape(action.memory_id)} пока пустое.",
        )
    elif mode == MEMORY_MODE_BATCH:
        delivered_count, delivery_note = await _deliver_memory_batch(
            self,
            chat_id,
            action.memory_id,
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

    if action.outro:
        await self._send_memory_text(chat_id, action.outro)

    token = secrets.token_urlsafe(8)
    await self.storage.set_progress(
        chat_id,
        step_id,
        action_index,
        waiting={
            "kind": MEMORY_ACK_WAITING_KIND,
            "token": token,
            "memory_id": action.memory_id,
            "next_index": next_index,
        },
        wrong_index=0,
    )

    warning = f"\n⚠️ {html.escape(delivery_note)}." if delivery_note else ""
    await self._send_memory_text(
        chat_id,
        f"↩️ <b>{MEMORY_FINISH_TITLE}</b>\n"
        "Когда дочитаешь, нажми «Прочитала» — после этого история продолжится."
        f"{warning}",
        reply_parameters=ReplyParameters(
            message_id=header_message.message_id,
            allow_sending_without_reply=True,
        ),
        reply_markup=_ack_keyboard(token),
    )

    logger.info(
        "Memory %s delivered to chat %s in %s mode and is waiting for acknowledgement: "
        "stored=%s delivered=%s note=%s",
        action.memory_id,
        chat_id,
        mode,
        len(messages),
        delivered_count,
        delivery_note,
    )
    return len(messages)


async def _execute_with_memory_ack(self, chat_id: int) -> None:
    """Run the quest until input, buttons, or a memory acknowledgement is required."""

    while True:
        progress = await self.storage.get_progress(chat_id)
        if progress is None:
            return
        step = self.roadmap.step(progress.step_id)
        if progress.action_index >= len(step.actions):
            await self.storage.clear_progress(chat_id)
            return

        action = step.actions[progress.action_index]
        next_index = progress.action_index + 1

        if isinstance(action, SendTextAction):
            await self._send_text(chat_id, action)
            await self.storage.set_progress(chat_id, step.id, next_index)
            continue

        if isinstance(action, MediaAction):
            await self._send_media(chat_id, action)
            await self.storage.set_progress(chat_id, step.id, next_index)
            continue

        if isinstance(action, DelayAction):
            await asyncio.sleep(action.seconds)
            await self.storage.set_progress(chat_id, step.id, next_index)
            continue

        if isinstance(action, MemoryAction):
            await _play_memory_and_wait(
                self,
                chat_id,
                action,
                step_id=step.id,
                action_index=progress.action_index,
                next_index=next_index,
            )
            return

        if isinstance(action, AskInputAction):
            if action.prompt:
                await self.bot.send_message(
                    chat_id,
                    action.prompt,
                    parse_mode=self._parse_mode(action.parse_mode),
                )
            await self.storage.set_progress(
                chat_id,
                step.id,
                progress.action_index,
                waiting={"kind": "input"},
                wrong_index=0,
            )
            return

        if isinstance(action, ButtonsAction):
            keyboard = self._keyboard(action)
            await self.bot.send_message(
                chat_id,
                action.text,
                parse_mode=self._parse_mode(action.parse_mode),
                reply_markup=keyboard,
            )
            await self.storage.set_progress(
                chat_id,
                step.id,
                progress.action_index,
                waiting={"kind": "buttons"},
            )
            return

        if isinstance(action, GotoAction):
            await self.storage.set_progress(chat_id, action.step_id, 0)
            continue

        raise RuntimeError(f"Unsupported action: {action}")


def _spawn_resume(self, chat_id: int) -> None:
    async def resume() -> None:
        try:
            await self._execute(chat_id)
        except Exception:
            logger.exception(
                "Quest continuation failed after memory acknowledgement in chat %s",
                chat_id,
            )

    tasks: set[asyncio.Task[Any]] = getattr(self, "_memory_resume_tasks", set())
    self._memory_resume_tasks = tasks
    task = asyncio.create_task(resume())
    tasks.add(task)
    task.add_done_callback(tasks.discard)


async def _handle_button_with_memory_ack(
    self,
    chat_id: int,
    button_id: str,
) -> tuple[bool, str]:
    if not button_id.startswith(MEMORY_ACK_CALLBACK_PREFIX):
        return await self._memory_ack_original_handle_button(chat_id, button_id)

    token = button_id.removeprefix(MEMORY_ACK_CALLBACK_PREFIX)
    locks: dict[int, asyncio.Lock] = getattr(self, "_memory_ack_locks", {})
    self._memory_ack_locks = locks
    lock = locks.setdefault(chat_id, asyncio.Lock())

    async with lock:
        progress = await self.storage.get_progress(chat_id)
        waiting = progress.waiting if progress is not None else None
        if (
            progress is None
            or not waiting
            or waiting.get("kind") != MEMORY_ACK_WAITING_KIND
            or waiting.get("token") != token
        ):
            return False, "Эта кнопка уже неактивна."

        try:
            next_index = int(waiting["next_index"])
        except (KeyError, TypeError, ValueError):
            logger.error(
                "Invalid memory acknowledgement state in chat %s: %r",
                chat_id,
                waiting,
            )
            return False, "Не удалось продолжить историю."

        await self.storage.set_progress(
            chat_id,
            progress.step_id,
            next_index,
        )

    _spawn_resume(self, chat_id)
    return True, "Продолжаем ✨"


def install_memory_read_ack(engine_module: Any) -> None:
    """Make every quest memory block until the participant confirms reading it."""

    engine_class = engine_module.QuestEngine
    if getattr(engine_class, "_memory_read_ack_installed", False):
        return

    # memory_modes owns preview/playback outside the quest execution loop. Wrap
    # its shared text sender too, so every memory final message uses the same
    # wording without duplicating the whole playback implementation.
    original_send_memory_text = engine_class._send_memory_text

    async def send_memory_text_with_restored_wording(
        self,
        chat_id: int,
        text: str,
        **kwargs: Any,
    ):
        text = text.replace(MEMORY_FINISH_OLD_TITLE, MEMORY_FINISH_TITLE)
        return await original_send_memory_text(self, chat_id, text, **kwargs)

    # Keep parse-mode selection on the class so the copied execution loop remains
    # independent from module globals and easy to test.
    engine_class._parse_mode = staticmethod(engine_module.parse_mode)
    engine_class._send_memory_text = send_memory_text_with_restored_wording
    engine_class._memory_ack_original_handle_button = engine_class.handle_button
    engine_class._execute = _execute_with_memory_ack
    engine_class.handle_button = _handle_button_with_memory_ack
    engine_class._memory_read_ack_installed = True
