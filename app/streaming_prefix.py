from __future__ import annotations

import asyncio
import html
import re
import secrets
from types import ModuleType
from typing import Any


_HTML_SPEAKER_PREFIX_RE = re.compile(
    r"^[ \t]*<b>[ \t]*(\[[^\]\r\n]+\])[ \t]*</b>[ \t]*(?:\r?\n){2,}"
)


def static_stream_prefix(value: str, parse_mode: str) -> str:
    """Return a visible speaker label that should not be typed character by character."""
    if parse_mode != "HTML":
        return ""
    match = _HTML_SPEAKER_PREFIX_RE.match(value)
    if match is None:
        return ""
    return f"{html.unescape(match.group(1))}\n\n"


def strip_static_stream_prefix(value: str, prefix: str, parse_mode: str, engine: ModuleType) -> str:
    """Convert a segment to plain draft text and remove one repeated static prefix."""
    visible = engine.plain_draft_text(value, parse_mode)
    if prefix and visible.startswith(prefix):
        return visible[len(prefix):]
    return visible


def install_static_speaker_prefix(engine: ModuleType) -> None:
    """Install static speaker-label handling on QuestEngine streamed messages."""

    async def _stream_text(self: Any, chat_id: int, action: Any) -> None:
        draft_id = secrets.randbelow(2_147_483_647) + 1
        segments = action.stream_segments or [
            {"text": action.text, "pause_after_seconds": 0}
        ]
        prefix = static_stream_prefix(action.text, action.parse_mode)
        accumulated = prefix
        last_draft_text = ""
        seconds_since_flush = 0.0
        sent_any_draft = False
        prefix_removed = False

        if prefix:
            if not await self._send_draft_update(chat_id, draft_id, prefix):
                return
            sent_any_draft = True
            last_draft_text = prefix

        for segment in segments:
            if isinstance(segment, dict):
                segment_text = str(segment.get("text", ""))
                pause_after = float(segment.get("pause_after_seconds", 0))
            else:
                segment_text = segment.text
                pause_after = segment.pause_after_seconds

            visible = engine.plain_draft_text(segment_text, action.parse_mode)
            if prefix and not prefix_removed and visible.startswith(prefix):
                visible = visible[len(prefix):]
                prefix_removed = True

            for piece in engine.stream_pieces(visible, action.delivery_mode):
                accumulated += piece
                await asyncio.sleep(action.typing_speed_seconds)
                seconds_since_flush += action.typing_speed_seconds

                if seconds_since_flush < engine.DRAFT_FLUSH_INTERVAL_SECONDS:
                    continue
                if not await self._send_draft_update(chat_id, draft_id, accumulated):
                    return
                sent_any_draft = True
                last_draft_text = accumulated
                seconds_since_flush = 0.0

            if pause_after and accumulated and accumulated != last_draft_text:
                if not await self._send_draft_update(chat_id, draft_id, accumulated):
                    return
                sent_any_draft = True
                last_draft_text = accumulated
                seconds_since_flush = 0.0
            if pause_after:
                await asyncio.sleep(pause_after)

        if not sent_any_draft:
            engine.logger.debug(
                "Streamed text in chat %s was shorter than the safe draft batch interval",
                chat_id,
            )

    engine.QuestEngine._stream_text = _stream_text
