from pathlib import Path

from app.video_normalization import (
    MAX_TELEGRAM_VIDEO_BYTES,
    _cache_path,
    prepare_video_for_telegram,
    target_video_bitrate,
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
