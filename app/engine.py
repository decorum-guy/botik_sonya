from __future__ import annotations

import asyncio
import html
import logging
import random
import re
import secrets
import time
from pathlib import Path

from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramRetryAfter,
)
from aiogram.types import FSInputFile, InlineKeyboardMarkup, Message

from app.button_styles import callback_button
from app.media_retry import retry_transient_telegram
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

# Telegram does not document a dedicated sendMessageDraft rate. Keep draft updates
# deliberately conservative and batch characters/words between API calls.
DRAFT_FLUSH_INTERVAL_SECONDS = 0.75
DRAFT_MIN_REQUEST_INTERVAL_SECONDS = 0.85
DRAFT_RETRY_ATTEMPTS = 5

# Human-looking pacing for reconstructed conversations. The legacy
# message_delay_seconds field remains accepted in ROADMAP files for backwards
# compatibility, but playback now always uses a fresh random value in this range.
MEMORY_MESSAGE_DELAY_MIN_SECONDS = 1.0
MEMORY_MESSAGE_DELAY_MAX_SECONDS = 3.5


def parse_mode(value: str):
    if value == "none":
        return None
    if value == "MarkdownV2":
        return ParseMode.MARKDOWN_V2
    return ParseMode.HTML


def plain_draft_text(value: str, mode: str) -> str:
    if mode == "HTML":
        return html.unescape(re.sub(r"<[^>]+>", "", value))
    if mode == "MarkdownV2":
        unescaped = re.sub(r"\\([_*\[\]()~`>#+\-=|{}.!])", r"\1", value)
        return re.sub(r"[*_~`]", "", unescaped)
    return value


def stream_pieces(value: str, mode: str) -> list[str]:
    if mode == "words":
        return re.findall(r"\S+\s*|\s+", value)
    return list(value)


def memory_message_delay_seconds() -> float:
    return random.uniform(
        MEMORY_MESSAGE_DELAY_MIN_SECONDS,
        MEMORY_MESSAGE_DELAY_MAX_SECONDS,
    )


class QuestEngine:
    def __init__(self, bot: Bot, storage: Storage, roadmap: Roadmap, root: Path) -> None:
        self.bot = bot
        self.storage = storage
        self.roadmap = roadmap
        self.root = root.resolve()
        self._draft_last_request_at: dict[int, float] = {}

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
                await self.play_memory(chat_id, action)
                await self.storage.set_progress(chat_id, step.id, next_index)
                continue

            if isinstance(action, AskInputAction):
                if action.prompt:
                    await self.bot.send_message(
                        chat_id,
                        action.prompt,
                        parse_mode=parse_mode(action.parse_mode),
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
        return True, selected.callback_text

    async def _send_memory_text(self, chat_id: int, text: str) -> None:
        await retry_transient_telegram(
            lambda: self.bot.send_message(chat_id, text),
            chat_id=chat_id,
            label="memory text",
        )

    async def _deliver_memory_message(
        self,
        chat_id: int,
        source_chat_id: int,
        source_message_id: int,
    ) -> None:
        try:
            await retry_transient_telegram(
                lambda: self.bot.forward_message(
                    chat_id=chat_id,
                    from_chat_id=source_chat_id,
                    message_id=source_message_id,
                ),
                chat_id=chat_id,
                label=f"memory forward #{source_message_id}",
            )
            return
        except (TelegramBadRequest, TelegramForbiddenError) as forward_exc:
            logger.warning(
                "Cannot forward memory message %s; trying copyMessage fallback: %s",
                source_message_id,
                forward_exc,
            )

        # copyMessage supports stickers, video notes and text with custom emoji,
        # but intentionally omits the Forwarded from header. It is a safer
        # fallback than a screenshot because animation and native Telegram media
        # remain intact.
        try:
            await retry_transient_telegram(
                lambda: self.bot.copy_message(
                    chat_id=chat_id,
                    from_chat_id=source_chat_id,
                    message_id=source_message_id,
                ),
                chat_id=chat_id,
                label=f"memory copy fallback #{source_message_id}",
            )
        except (TelegramBadRequest, TelegramForbiddenError) as copy_exc:
            logger.exception(
                "Cannot forward or copy memory message %s: %s",
                source_message_id,
                copy_exc,
            )
            await self._send_memory_text(
                chat_id,
                f"⚠️ Не удалось восстановить сохранённый фрагмент #{source_message_id}.",
            )
        else:
            logger.info(
                "Memory message %s delivered via copyMessage fallback",
                source_message_id,
            )

    async def play_memory(self, chat_id: int, action: MemoryAction) -> None:
        header = (
            f"<b>{html.escape(action.title)} {action.number}/{action.total}</b>\n\n"
            f"{html.escape(action.date_text)}\n"
            "━━━━━━━━━━━━━━━━━━━━"
        )
        await self._send_memory_text(chat_id, header)
        if action.intro:
            await self._send_memory_text(chat_id, action.intro)
        messages = await self.storage.memory_messages(action.memory_id)
        if not messages:
            await self._send_memory_text(
                chat_id,
                f"[Тест] Воспоминание {html.escape(action.memory_id)} пока пустое.",
            )
            return

        for index, (_, source_chat_id, source_message_id, _, _) in enumerate(messages):
            await self._deliver_memory_message(
                chat_id,
                source_chat_id,
                source_message_id,
            )
            if index < len(messages) - 1:
                await asyncio.sleep(memory_message_delay_seconds())

        if action.outro:
            await self._send_memory_text(chat_id, action.outro)

    async def preview_memory(self, destination_chat_id: int, memory_id: str) -> int:
        messages = await self.storage.memory_messages(memory_id)
        for index, (_, source_chat_id, source_message_id, _, _) in enumerate(messages):
            await self._deliver_memory_message(
                destination_chat_id,
                source_chat_id,
                source_message_id,
            )
            if index < len(messages) - 1:
                await asyncio.sleep(memory_message_delay_seconds())
        return len(messages)

    async def _send_text(self, chat_id: int, action: SendTextAction) -> None:
        if action.delivery_mode != "instant":
            await self._stream_text(chat_id, action)
        await self._send_final_text(chat_id, action)

    async def _send_final_text(self, chat_id: int, action: SendTextAction) -> None:
        for attempt in range(1, DRAFT_RETRY_ATTEMPTS + 1):
            try:
                await self.bot.send_message(
                    chat_id,
                    action.text,
                    parse_mode=parse_mode(action.parse_mode),
                    disable_notification=action.disable_notification,
                )
                return
            except TelegramRetryAfter as exc:
                if attempt == DRAFT_RETRY_ATTEMPTS:
                    raise
                delay = max(float(exc.retry_after), 0) + 0.25
                logger.warning(
                    "Telegram throttled final streamed message in chat %s; retrying in %.2fs",
                    chat_id,
                    delay,
                )
                await asyncio.sleep(delay)

    async def _stream_text(self, chat_id: int, action: SendTextAction) -> None:
        draft_id = secrets.randbelow(2_147_483_647) + 1
        segments = action.stream_segments or [
            {"text": action.text, "pause_after_seconds": 0}
        ]
        accumulated = ""
        last_draft_text = ""
        seconds_since_flush = 0.0
        sent_any_draft = False

        for segment in segments:
            if isinstance(segment, dict):
                segment_text = str(segment.get("text", ""))
                pause_after = float(segment.get("pause_after_seconds", 0))
            else:
                segment_text = segment.text
                pause_after = segment.pause_after_seconds

            visible = plain_draft_text(segment_text, action.parse_mode)
            for piece in stream_pieces(visible, action.delivery_mode):
                accumulated += piece
                await asyncio.sleep(action.typing_speed_seconds)
                seconds_since_flush += action.typing_speed_seconds

                if seconds_since_flush < DRAFT_FLUSH_INTERVAL_SECONDS:
                    continue
                if not await self._send_draft_update(chat_id, draft_id, accumulated):
                    return
                sent_any_draft = True
                last_draft_text = accumulated
                seconds_since_flush = 0.0

            # A segment pause is meaningful only if the user can see the complete
            # segment before the pause starts, so flush at that boundary.
            if pause_after and accumulated and accumulated != last_draft_text:
                if not await self._send_draft_update(chat_id, draft_id, accumulated):
                    return
                sent_any_draft = True
                last_draft_text = accumulated
                seconds_since_flush = 0.0
            if pause_after:
                await asyncio.sleep(pause_after)

        # Do not send a last draft update immediately before sendMessage. The
        # permanent final message follows next and avoids one extra flood-prone call.
        if not sent_any_draft:
            logger.debug(
                "Streamed text in chat %s was shorter than the safe draft batch interval",
                chat_id,
            )

    async def _send_draft_update(self, chat_id: int, draft_id: int, text: str) -> bool:
        for attempt in range(1, DRAFT_RETRY_ATTEMPTS + 1):
            last_request = self._draft_last_request_at.get(chat_id, 0.0)
            remaining = DRAFT_MIN_REQUEST_INTERVAL_SECONDS - (time.monotonic() - last_request)
            if remaining > 0:
                await asyncio.sleep(remaining)

            self._draft_last_request_at[chat_id] = time.monotonic()
            try:
                await self.bot.send_message_draft(
                    chat_id=chat_id,
                    draft_id=draft_id,
                    text=text,
                )
                return True
            except TelegramRetryAfter as exc:
                delay = max(float(exc.retry_after), 0) + 0.25
                logger.warning(
                    "Telegram throttled sendMessageDraft in chat %s; retry %s/%s in %.2fs",
                    chat_id,
                    attempt,
                    DRAFT_RETRY_ATTEMPTS,
                    delay,
                )
                await asyncio.sleep(delay)
            except (AttributeError, TelegramBadRequest) as exc:
                logger.warning("Streaming draft unavailable, using final message only: %s", exc)
                return False

        logger.warning(
            "Streaming draft stopped after %s flood-control retries; final message will still be sent",
            DRAFT_RETRY_ATTEMPTS,
        )
        return False

    def _keyboard(self, action: ButtonsAction) -> InlineKeyboardMarkup:
        rows = []
        for index in range(0, len(action.buttons), action.columns):
            rows.append([
                callback_button(
                    text=button.text,
                    callback_data=f"quest:{button.id}",
                    style=button.style,
                )
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
