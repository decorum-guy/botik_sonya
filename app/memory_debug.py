from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _enum_value(value: Any) -> Any:
    return getattr(value, "value", value)


def _entity_dump(entity: Any) -> dict[str, Any]:
    return {
        "type": str(_enum_value(getattr(entity, "type", ""))),
        "offset": getattr(entity, "offset", None),
        "length": getattr(entity, "length", None),
        "custom_emoji_id": getattr(entity, "custom_emoji_id", None),
    }


def _file_unique_ids(message: Message) -> list[str]:
    photo = message.photo[-1] if message.photo else None
    candidates = (
        photo,
        message.video,
        message.animation,
        message.document,
        message.audio,
        message.voice,
        message.video_note,
        message.sticker,
    )
    return [
        file_unique_id
        for item in candidates
        if item is not None
        if (file_unique_id := getattr(item, "file_unique_id", None))
    ]


def message_debug_payload(message: Message) -> dict[str, Any]:
    sticker = message.sticker
    video_note = message.video_note
    origin = message.forward_origin
    return {
        "chat_id": message.chat.id,
        "from_user_id": message.from_user.id if message.from_user else None,
        "message_id": message.message_id,
        "date": message.date.isoformat() if message.date else None,
        "content_type": str(_enum_value(message.content_type)),
        "media_group_id": message.media_group_id,
        "forward_origin_type": type(origin).__name__ if origin is not None else None,
        "text_preview": (message.text or "")[:500] or None,
        "caption_preview": (message.caption or "")[:500] or None,
        "entities": [_entity_dump(item) for item in (message.entities or [])],
        "caption_entities": [
            _entity_dump(item) for item in (message.caption_entities or [])
        ],
        "has_video_note": video_note is not None,
        "video_note_duration": getattr(video_note, "duration", None),
        "video_note_length": getattr(video_note, "length", None),
        "has_sticker": sticker is not None,
        "sticker_type": (
            str(_enum_value(getattr(sticker, "type", ""))) if sticker else None
        ),
        "sticker_is_animated": getattr(sticker, "is_animated", None),
        "sticker_is_video": getattr(sticker, "is_video", None),
        "sticker_has_premium_animation": (
            getattr(sticker, "premium_animation", None) is not None if sticker else None
        ),
        "sticker_custom_emoji_id": getattr(sticker, "custom_emoji_id", None),
        "file_unique_ids": _file_unique_ids(message),
    }


@dataclass(slots=True)
class DebugSession:
    path: Path
    started_at: str
    events: int = 0
    seen_incoming: set[str] = field(default_factory=set)


class MemoryDebugRecorder:
    def __init__(self) -> None:
        self._sessions: dict[int, DebugSession] = {}
        self._lock = asyncio.Lock()

    async def start(self, admin_id: int, directory: Path) -> DebugSession:
        async with self._lock:
            existing = self._sessions.get(admin_id)
            if existing is not None:
                return existing

            directory.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
            path = directory / f"memory-debug-{admin_id}-{stamp}.jsonl"
            session = DebugSession(path=path, started_at=_utc_now())
            self._sessions[admin_id] = session
            self._append_unlocked(
                session,
                {
                    "timestamp": _utc_now(),
                    "event": "debug_started",
                    "admin_id": admin_id,
                    "format_version": 1,
                },
            )
            return session

    async def stop(self, admin_id: int) -> DebugSession | None:
        async with self._lock:
            session = self._sessions.pop(admin_id, None)
            if session is None:
                return None
            self._append_unlocked(
                session,
                {
                    "timestamp": _utc_now(),
                    "event": "debug_stopped",
                    "admin_id": admin_id,
                    "recorded_events": session.events,
                    "unique_incoming_messages": len(session.seen_incoming),
                },
            )
            return session

    async def status(self, admin_id: int) -> DebugSession | None:
        async with self._lock:
            return self._sessions.get(admin_id)

    async def record_incoming(
        self,
        admin_id: int,
        message: Message,
        *,
        update_id: int | None,
    ) -> None:
        async with self._lock:
            session = self._sessions.get(admin_id)
            if session is None:
                return
            key = (
                f"update:{update_id}"
                if update_id is not None
                else f"message:{message.chat.id}:{message.message_id}"
            )
            if key in session.seen_incoming:
                return
            session.seen_incoming.add(key)
            self._append_unlocked(
                session,
                {
                    "timestamp": _utc_now(),
                    "event": "incoming_message",
                    "update_id": update_id,
                    "message": message_debug_payload(message),
                },
            )

    async def record(
        self,
        admin_id: int,
        event: str,
        **payload: Any,
    ) -> None:
        async with self._lock:
            session = self._sessions.get(admin_id)
            if session is None:
                return
            self._append_unlocked(
                session,
                {
                    "timestamp": _utc_now(),
                    "event": event,
                    **payload,
                },
            )

    def _append_unlocked(self, session: DebugSession, payload: dict[str, Any]) -> None:
        with session.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")
        session.events += 1


memory_debug = MemoryDebugRecorder()


class MemoryDebugMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if not isinstance(event, Message) or event.from_user is None:
            return await handler(event, data)

        admin_id = event.from_user.id
        update = data.get("event_update")
        await memory_debug.record_incoming(
            admin_id,
            event,
            update_id=getattr(update, "update_id", None),
        )
        try:
            return await handler(event, data)
        except Exception as exc:
            await memory_debug.record(
                admin_id,
                "handler_exception",
                update_id=getattr(update, "update_id", None),
                message_id=event.message_id,
                exception_type=type(exc).__name__,
                exception=str(exc),
            )
            raise
