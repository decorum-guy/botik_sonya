from __future__ import annotations

import asyncio
import html
import logging
from pathlib import Path

from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import FSInputFile, InlineKeyboardMarkup, Message

from app.button_styles import callback_button
from app.models import (
    AskInputAction,
    ButtonsAction,
    DelayAction,
    GotoAction,
    MediaAction,
    MemoryAction,
    Roadmap,
    SendTextAction,
)
from app.storage import Storage
from app.validation import validate_answer

logger = logging.getLogger(__name__)


def parse_mode(value: str):
    if value == "none":
        return None
    if value == "MarkdownV2":
        return ParseMode.MARKDOWN_V2
    return ParseMode.HTML


class QuestEngine:
    def __init__(self, bot: Bot, storage: Storage, roadmap: Roadmap, root: Path) -> None:
        self.bot = bot
        self.storage = storage
        self.roadmap = roadmap
        self.root = root.resolve()

    async def start(self, chat_id: int, step_id: str | None = None) -> None:
        target = step_id or self.roadmap.meta.entry_step_id
        await self.storage.set_progress(chat_id, target, 0)
        await self._execute(chat_id)

    async def _execute(self, chat_id: int) -> None:
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
                await self.bot.send_message(
                    chat_id,
                    action.text,
                    parse_mode=parse_mode(action.parse_mode),
                    disable_notification=action.disable_notification,
                )
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
                await self.play_memory(chat_id, action)
                await self.storage.set_progress(chat_id, step.id, next_index)
                continue

            if isinstance(action, AskInputAction):
                if action.prompt:
                    await self.bot.send_message(chat_id, action.prompt, parse_mode=parse_mode(action.parse_mode))
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
                    parse_mode=parse_mode(action.parse_mode),
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

    async def handle_answer(self, message: Message) -> bool:
        progress = await self.storage.get_progress(message.chat.id)
        if not progress or not progress.waiting or progress.waiting.get("kind") != "input":
            return False
        step = self.roadmap.step(progress.step_id)
        action = step.actions[progress.action_index]
        if not isinstance(action, AskInputAction):
            return False
        raw = message.text or message.caption or ""
        if validate_answer(raw, action.validator):
            if action.success_text:
                await message.answer(action.success_text, parse_mode=parse_mode(action.parse_mode))
            if action.next_step:
                await self.storage.set_progress(message.chat.id, action.next_step, 0)
            else:
                await self.storage.set_progress(message.chat.id, step.id, progress.action_index + 1)
            await self._execute(message.chat.id)
            return True

        hints = action.wrong_answers or ["Пока не совпало. Попробуй ещё раз."]
        hint = hints[min(progress.wrong_index, len(hints) - 1)]
        await message.answer(hint, parse_mode=parse_mode(action.parse_mode))
        await self.storage.set_progress(
            message.chat.id,
            step.id,
            progress.action_index,
            waiting=progress.waiting,
            wrong_index=progress.wrong_index + 1,
        )
        return True

    async def handle_button(self, chat_id: int, button_id: str) -> tuple[bool, str]:
        progress = await self.storage.get_progress(chat_id)
        if not progress or not progress.waiting or progress.waiting.get("kind") != "buttons":
            return False, "Эта кнопка уже неактивна."
        step = self.roadmap.step(progress.step_id)
        action = step.actions[progress.action_index]
        if not isinstance(action, ButtonsAction):
            return False, "Эта кнопка уже неактивна."
        selected = next((button for button in action.buttons if button.id == button_id), None)
        if selected is None:
            return False, "Неизвестная кнопка."
        if selected.answer_text:
            await self.bot.send_message(chat_id, selected.answer_text)
        if selected.next_step:
            await self.storage.set_progress(chat_id, selected.next_step, 0)
        else:
            await self.storage.set_progress(chat_id, step.id, progress.action_index + 1)
        await self._execute(chat_id)
        return True, ""

    async def play_memory(self, chat_id: int, action: MemoryAction) -> None:
        header = (
            f"<b>{html.escape(action.title)} {action.number}/{action.total}</b>\n\n"
            f"{html.escape(action.date_text)}\n"
            "━━━━━━━━━━━━━━━━━━━━"
        )
        await self.bot.send_message(chat_id, header)
        if action.intro:
            await self.bot.send_message(chat_id, action.intro)
        messages = await self.storage.memory_messages(action.memory_id)
        if not messages:
            await self.bot.send_message(chat_id, f"[Тест] Воспоминание {html.escape(action.memory_id)} пока пустое.")
            return
        for _, source_chat_id, source_message_id, _, _ in messages:
            try:
                await self.bot.forward_message(
                    chat_id=chat_id,
                    from_chat_id=source_chat_id,
                    message_id=source_message_id,
                )
            except (TelegramBadRequest, TelegramForbiddenError) as exc:
                logger.exception("Cannot forward memory message %s: %s", source_message_id, exc)
                await self.bot.send_message(
                    chat_id,
                    f"⚠️ Не удалось переслать сохранённый фрагмент #{source_message_id}.",
                )
            if action.message_delay_seconds:
                await asyncio.sleep(action.message_delay_seconds)
        if action.outro:
            await self.bot.send_message(chat_id, action.outro)

    async def preview_memory(self, destination_chat_id: int, memory_id: str) -> int:
        messages = await self.storage.memory_messages(memory_id)
        for _, source_chat_id, source_message_id, _, _ in messages:
            await self.bot.forward_message(
                chat_id=destination_chat_id,
                from_chat_id=source_chat_id,
                message_id=source_message_id,
            )
            await asyncio.sleep(0.25)
        return len(messages)

    def _keyboard(self, action: ButtonsAction) -> InlineKeyboardMarkup:
        rows = []
        for index in range(0, len(action.buttons), action.columns):
            rows.append([
                callback_button(text=button.text, callback_data=f"quest:{button.id}", style=button.style)
                for button in action.buttons[index:index + action.columns]
            ])
        return InlineKeyboardMarkup(inline_keyboard=rows)

    def _safe_media_path(self, relative: str) -> Path:
        path = (self.root / relative).resolve()
        if self.root not in path.parents or not path.is_file():
            raise FileNotFoundError(f"Media file not found or outside repository: {relative}")
        return path

    async def _send_media(self, chat_id: int, action: MediaAction) -> None:
        file = FSInputFile(self._safe_media_path(action.path))
        kwargs = {
            "chat_id": chat_id,
            "caption": action.caption or None,
            "parse_mode": parse_mode(action.parse_mode),
            "disable_notification": action.disable_notification,
        }
        if action.type == "send_photo":
            await self.bot.send_photo(photo=file, **kwargs)
        elif action.type == "send_video":
            await self.bot.send_video(video=file, supports_streaming=True, **kwargs)
        elif action.type == "send_audio":
            await self.bot.send_audio(audio=file, **kwargs)
        elif action.type == "send_document":
            await self.bot.send_document(document=file, **kwargs)
