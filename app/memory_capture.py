from __future__ import annotations

import asyncio
import html
from typing import Any

from aiogram.types import Message

from app.memory_debug import memory_debug
from app.storage import Storage


_capture_locks: dict[tuple[int, str], asyncio.Lock] = {}


def _entity_type_value(entity: Any) -> str:
    value = getattr(entity, "type", "")
    return str(getattr(value, "value", value))


def custom_emoji_count(message: Message) -> int:
    entities = list(message.entities or []) + list(message.caption_entities or [])
    return sum(_entity_type_value(entity) == "custom_emoji" for entity in entities)


def memory_content_label(message: Message) -> str:
    """Return a human-readable label for rich Telegram memory content."""

    if message.video_note is not None:
        return "кружок · video_note"

    sticker = message.sticker
    if sticker is not None:
        sticker_type = str(
            getattr(
                getattr(sticker, "type", ""),
                "value",
                getattr(sticker, "type", ""),
            )
        )
        if getattr(sticker, "premium_animation", None) is not None:
            return "premium-стикер"
        if sticker_type == "custom_emoji":
            return "стикер custom_emoji"
        if getattr(sticker, "is_video", False):
            return "видео-стикер"
        if getattr(sticker, "is_animated", False):
            return "анимированный стикер"
        return "стикер"

    emoji_count = custom_emoji_count(message)
    if emoji_count:
        return f"текст с пользовательскими эмоджи ×{emoji_count}"

    return str(message.content_type)


def is_command_message(message: Message) -> bool:
    text = (message.text or "").lstrip()
    return text.startswith("/")


def _capture_lock(storage: Storage, memory_id: str) -> asyncio.Lock:
    key = (id(storage), memory_id)
    lock = _capture_locks.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _capture_locks[key] = lock
    return lock


async def _debug_record(message: Message, event: str, **payload: Any) -> None:
    if message.from_user is None:
        return
    await memory_debug.record(
        message.from_user.id,
        event,
        message_id=message.message_id,
        **payload,
    )


async def _safe_answer(message: Message, text: str) -> None:
    try:
        await message.answer(text)
    except Exception as exc:  # noqa: BLE001 - acknowledgement must not lose captured data
        await _debug_record(
            message,
            "capture_ack_failed",
            exception_type=type(exc).__name__,
            exception=str(exc),
        )


async def capture_memory_message(
    storage: Storage,
    message: Message,
    memory_id: str,
    *,
    finish_command: str,
) -> int | None:
    """Store a Telegram message as a memory fragment without burst losses.

    Telegram can deliver a bulk forward as many updates almost simultaneously.
    The per-memory lock serializes the old ``MAX(position) + 1`` storage operation,
    preventing concurrent handlers from selecting the same primary-key position.
    """

    if is_command_message(message):
        await _debug_record(
            message,
            "capture_ignored_command",
            memory_id=memory_id,
            command=(message.text or "")[:200],
        )
        await _safe_answer(
            message,
            "Команда не добавлена во воспоминание. "
            f"Для завершения используй {html.escape(finish_command)}.",
        )
        return None

    origin = message.forward_origin
    origin_label = type(origin).__name__ if origin is not None else "NoForwardOrigin"
    content_label = memory_content_label(message)

    try:
        async with _capture_lock(storage, memory_id):
            existing_position = next(
                (
                    position
                    for position, source_chat_id, source_message_id, _, _
                    in await storage.memory_messages(memory_id)
                    if source_chat_id == message.chat.id
                    and source_message_id == message.message_id
                ),
                None,
            )
            if existing_position is not None:
                await _debug_record(
                    message,
                    "capture_duplicate",
                    memory_id=memory_id,
                    position=existing_position,
                    content_label=content_label,
                )
                return existing_position

            position = await storage.add_memory_message(
                memory_id=memory_id,
                source_chat_id=message.chat.id,
                source_message_id=message.message_id,
                content_type=str(message.content_type),
                origin_label=f"{origin_label}|{content_label}",
            )
    except Exception as exc:
        await _debug_record(
            message,
            "capture_failed",
            memory_id=memory_id,
            content_label=content_label,
            exception_type=type(exc).__name__,
            exception=str(exc),
        )
        raise

    await _debug_record(
        message,
        "capture_saved",
        memory_id=memory_id,
        position=position,
        content_label=content_label,
        content_type=str(message.content_type),
        media_group_id=message.media_group_id,
        forward_origin_type=type(origin).__name__ if origin is not None else None,
    )

    origin_note = "" if origin is not None else " · без метки origin, но сохранено"
    await _safe_answer(
        message,
        f"Сохранено #{position}: <code>{html.escape(content_label)}</code>{origin_note}. "
        f"Когда закончишь — {html.escape(finish_command)}.",
    )
    return position
