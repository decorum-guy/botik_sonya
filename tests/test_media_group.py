from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest
from aiogram.types import InputMediaPhoto, InputMediaVideo
from pydantic import ValidationError

import app.photo_normalization as photo_normalization
from app.media_group import (
    MediaGroupItem,
    encode_media_group_path,
    parse_media_group_path,
)
from app.models import MediaAction


def test_media_group_path_round_trip() -> None:
    encoded = encode_media_group_path(
        [
            MediaGroupItem(kind="photo", path="media/one.jpg"),
            MediaGroupItem(kind="video", path="media/two.mp4"),
        ]
    )

    assert parse_media_group_path(encoded) == [
        MediaGroupItem(kind="photo", path="media/one.jpg"),
        MediaGroupItem(kind="video", path="media/two.mp4"),
    ]


def test_media_group_rejects_unsafe_or_wrong_item_count() -> None:
    with pytest.raises(ValueError, match="2-6"):
        parse_media_group_path("album:v1\nphoto\tmedia/only.jpg")

    with pytest.raises(ValueError, match="safe repository-relative"):
        parse_media_group_path(
            "album:v1\nphoto\tmedia/one.jpg\nvideo\t../outside.mp4"
        )


def test_media_action_validates_media_group_payload() -> None:
    action = MediaAction(
        type="send_photo",
        path="album:v1\nphoto\tmedia/one.jpg\nvideo\tmedia/two.mp4",
    )
    assert len(parse_media_group_path(action.path)) == 2

    with pytest.raises(ValidationError):
        MediaAction(
            type="send_photo",
            path="album:v1\nphoto\tmedia/only.jpg",
        )


def test_send_media_group_normalizes_photos_and_prepares_videos(
    tmp_path: Path,
    monkeypatch,
) -> None:
    photo = tmp_path / "media" / "one.heic"
    video = tmp_path / "media" / "two.mp4"
    photo.parent.mkdir()
    photo.write_bytes(b"photo")
    video.write_bytes(b"video")

    monkeypatch.setattr(photo_normalization, "normalize_photo_bytes", lambda path: b"jpeg")
    monkeypatch.setattr(
        photo_normalization,
        "prepare_video_for_telegram",
        lambda path, cache_dir: path,
    )

    class FakeBot:
        def __init__(self) -> None:
            self.calls = []

        async def send_media_group(self, **kwargs):
            self.calls.append(kwargs)

    class FakeEngine:
        def __init__(self) -> None:
            self.root = tmp_path
            self.bot = FakeBot()

        def _safe_media_path(self, relative: str) -> Path:
            return self.root / relative

    action = SimpleNamespace(
        path="album:v1\nphoto\tmedia/one.heic\nvideo\tmedia/two.mp4",
        caption="Общая подпись",
        parse_mode="HTML",
        disable_notification=True,
    )
    engine_module = SimpleNamespace(parse_mode=lambda value: value)
    engine = FakeEngine()

    asyncio.run(
        photo_normalization._send_media_group(
            engine,
            chat_id=123,
            action=action,
            engine_module=engine_module,
        )
    )

    call = engine.bot.calls[0]
    assert call["chat_id"] == 123
    assert call["disable_notification"] is True
    assert len(call["media"]) == 2
    assert isinstance(call["media"][0], InputMediaPhoto)
    assert isinstance(call["media"][1], InputMediaVideo)
    assert call["media"][0].caption == "Общая подпись"
    assert call["media"][1].caption is None
