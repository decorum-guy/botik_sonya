from pathlib import Path

import tools.prepare_media as prepare_media


def test_find_videos_recursively_and_ignore_other_files(tmp_path: Path) -> None:
    media = tmp_path / "media"
    nested = media / "nested"
    nested.mkdir(parents=True)
    (media / "one.mp4").write_bytes(b"video")
    (nested / "two.MOV").write_bytes(b"video")
    (nested / "note.txt").write_text("not video")

    found = prepare_media.find_videos(media)

    assert found == sorted([media / "one.mp4", nested / "two.MOV"])


def test_prepare_only_oversized_videos(tmp_path: Path, monkeypatch) -> None:
    media = tmp_path / "media"
    cache = tmp_path / "cache"
    media.mkdir()
    small = media / "small.mp4"
    large = media / "large.mp4"
    small.write_bytes(b"s" * 10)
    large.write_bytes(b"l" * 100)
    monkeypatch.setattr(prepare_media, "MAX_TELEGRAM_VIDEO_BYTES", 50)

    calls: list[Path] = []

    def fake_prepare(source: Path, cache_dir: Path) -> Path:
        calls.append(source)
        cache_dir.mkdir(parents=True, exist_ok=True)
        destination = cache_dir / f"{source.stem}-prepared.mp4"
        destination.write_bytes(b"ready")
        return destination

    monkeypatch.setattr(prepare_media, "prepare_video_for_telegram", fake_prepare)

    prepared, skipped, failed = prepare_media.prepare_oversized_videos(media, cache)

    assert calls == [large]
    assert skipped == [small]
    assert failed == []
    assert len(prepared) == 1
    assert prepared[0].source == large
    assert prepared[0].prepared == cache / "large-prepared.mp4"


def test_dry_run_does_not_encode(tmp_path: Path, monkeypatch) -> None:
    media = tmp_path / "media"
    media.mkdir()
    large = media / "large.mp4"
    large.write_bytes(b"l" * 100)
    monkeypatch.setattr(prepare_media, "MAX_TELEGRAM_VIDEO_BYTES", 50)

    def fail_if_called(source: Path, cache_dir: Path) -> Path:
        raise AssertionError(f"unexpected encode: {source} -> {cache_dir}")

    monkeypatch.setattr(prepare_media, "prepare_video_for_telegram", fail_if_called)

    prepared, skipped, failed = prepare_media.prepare_oversized_videos(
        media,
        tmp_path / "cache",
        dry_run=True,
    )

    assert prepared == []
    assert skipped == []
    assert failed == []
