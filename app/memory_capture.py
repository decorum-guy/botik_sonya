from __future__ import annotations

import html
from typing import Any

from aiogram.types import Message

from app.storage import Storage


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
        sticker_type = str(getattr(getattr(sticker, "type", ""), "value", getattr(sticker, "type", "")))
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


async def capture_memory_message(
    storage: Storage,
    message: Message,
    memory_id: str,
    *,
    finish_command: str,
) -> int | None:
    """Store any ordinary message from the admin-bot chat as a memory fragment.

    The source that is replayed later is the message already delivered to the bot
    chat. Telegram doesn't consistently expose ``forward_origin`` for every rich
    message/client combination, so its absence must not reject video notes,
    stickers or messages containing custom emoji.
    """

    if is_command_message(message):
        await message.answer(
            "Команда не добавлена во воспоминание. "
            f"Для завершения используй {html.escape(finish_command)}."
        )
        return None

    origin = message.forward_origin
    origin_label = type(origin).__name__ if origin is not None else "NoForwardOrigin"
    content_label = memory_content_label(message)

    position = await storage.add_memory_message(
        memory_id=memory_id,
        source_chat_id=message.chat.id,
        source_message_id=message.message_id,
        content_type=str(message.content_type),
        origin_label=f"{origin_label}|{content_label}",
    )

    origin_note = "" if origin is not None else " · без метки origin, но сохранено"
    await message.answer(
        f"Сохранено #{position}: <code>{html.escape(content_label)}</code>{origin_note}. "
        f"Когда закончишь — {html.escape(finish_command)}."
    )
    return position
