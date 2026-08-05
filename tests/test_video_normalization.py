import shutil
from pathlib import Path

import app.video_normalization as video_normalization
from app.video_normalization import (
    MAX_TELEGRAM_VIDEO_BYTES,
    VideoMetadata,
    _cache_path,
    prepare_video_for_telegram,
    probe_video_metadata,
    target_video_bitrate,
    video_send_kwargs,
)


def test_small_video_is_sent_without_reencoding(tmp_path: Path) -> None:
    source = tmp_path / "small.mp4"
    source.write_bytes(b"0" * 1024)

    prepared = prepare_video_for_telegram(source, tmp_path / "cache")

    assert prepared == source
    assert not (tmp_path / "cache").exists()


def test_target_bitrate_keeps_eighty_second_video_below_limit() -> None:
    bitrate = target_video_bitrate(80.3)

    assert 4_000_000 < bitrate < 5_000_000
    estimated_bytes = int((bitrate + 96_000) * 80.3 / 8)
    assert estimated_bytes < MAX_TELEGRAM_VIDEO_BYTES


def test_cache_key_changes_when_source_changes(tmp_path: Path) -> None:
    source = tmp_path / "video.mp4"
    cache = tmp_path / "cache"
    source.write_bytes(b"first")
    first = _cache_path(source, cache)

    source.write_bytes(b"second version")
    second = _cache_path(source, cache)

    assert first != second


def test_cache_key_survives_project_move_when_copy_preserves_metadata(tmp_path: Path) -> None:
    first_dir = tmp_path / "mac" / "media"
    second_dir = tmp_path / "server" / "media"
    first_dir.mkdir(parents=True)
    second_dir.mkdir(parents=True)
    first = first_dir / "vertical.mp4"
    second = second_dir / "vertical.mp4"
    first.write_bytes(b"portable-video-content")
    shutil.copy2(first, second)

    assert _cache_path(first, tmp_path / "cache-a").name == _cache_path(
        second,
        tmp_path / "cache-b",
    ).name


def test_probe_video_metadata_applies_rotation(monkeypatch, tmp_path: Path) -> None:
    source = tmp_path / "capcut.mp4"
    source.write_bytes(b"video")
    monkeypatch.setattr(
        video_normalization,
        "_ffprobe_payload",
        lambda path: {
            "streams": [
                {
                    "width": 1920,
                    "height": 1080,
                    "tags": {"rotate": "90"},
                }
            ],
            "format": {"duration": "7.2"},
        },
    )

    assert probe_video_metadata(source) == VideoMetadata(
        width=1080,
        height=1920,
        duration=8,
    )
    assert video_send_kwargs(source) == {
        "width": 1080,
        "height": 1920,
        "duration": 8,
    }
