from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from app.video_normalization import (
    MAX_TELEGRAM_VIDEO_BYTES,
    prepare_video_for_telegram,
)

VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".mkv", ".webm"}


@dataclass(frozen=True)
class PreparedVideo:
    source: Path
    prepared: Path
    source_bytes: int
    prepared_bytes: int
    elapsed_seconds: float


def human_size(size: int) -> str:
    units = ("B", "KB", "MB", "GB")
    value = float(size)
    for unit in units:
        if value < 1000 or unit == units[-1]:
            return f"{value:.1f} {unit}"
        value /= 1000
    return f"{value:.1f} GB"


def find_videos(media_dir: Path) -> list[Path]:
    return sorted(
        path
        for path in media_dir.rglob("*")
        if path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS
    )


def prepare_oversized_videos(
    media_dir: Path,
    cache_dir: Path,
    *,
    dry_run: bool = False,
) -> tuple[list[PreparedVideo], list[Path], list[tuple[Path, Exception]]]:
    prepared: list[PreparedVideo] = []
    skipped: list[Path] = []
    failed: list[tuple[Path, Exception]] = []

    for source in find_videos(media_dir):
        source_bytes = source.stat().st_size
        if source_bytes <= MAX_TELEGRAM_VIDEO_BYTES:
            skipped.append(source)
            print(f"SKIP  {source}: {human_size(source_bytes)}")
            continue

        print(
            f"PREP  {source}: {human_size(source_bytes)} "
            f"(лимит {human_size(MAX_TELEGRAM_VIDEO_BYTES)})"
        )
        if dry_run:
            continue

        started = time.monotonic()
        try:
            destination = prepare_video_for_telegram(source, cache_dir)
        except Exception as exc:  # noqa: BLE001 - report every media failure together
            failed.append((source, exc))
            print(f"FAIL  {source}: {exc}", file=sys.stderr)
            continue

        elapsed = time.monotonic() - started
        result = PreparedVideo(
            source=source,
            prepared=destination,
            source_bytes=source_bytes,
            prepared_bytes=destination.stat().st_size,
            elapsed_seconds=elapsed,
        )
        prepared.append(result)
        print(
            f"READY {source.name}: {human_size(source_bytes)} -> "
            f"{human_size(result.prepared_bytes)} за {elapsed:.1f} сек.\n"
            f"      Кэш: {destination}"
        )

    return prepared, skipped, failed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Заранее подготавливает крупные видео для Telegram и заполняет "
            "кэш, используемый ботом во время квеста."
        )
    )
    parser.add_argument(
        "--media-dir",
        type=Path,
        default=Path("media"),
        help="Папка с медиа относительно текущего каталога (по умолчанию: media).",
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=Path(".cache/telegram_media"),
        help=(
            "Кэш готовых файлов. Должен совпадать с кэшем движка "
            "(по умолчанию: .cache/telegram_media)."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Только показать, какие видео требуют подготовки.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    media_dir = args.media_dir.expanduser().resolve()
    cache_dir = args.cache_dir.expanduser().resolve()

    if not media_dir.is_dir():
        print(f"Папка с медиа не найдена: {media_dir}", file=sys.stderr)
        return 2

    videos = find_videos(media_dir)
    if not videos:
        print(f"Видео в {media_dir} не найдены.")
        return 0

    print(f"Проверяю {len(videos)} видео в {media_dir}")
    print(
        "Важно: сначала перенеси проект в окончательную папку. "
        "Кэш привязан к полному пути исходного файла."
    )

    prepared, skipped, failed = prepare_oversized_videos(
        media_dir,
        cache_dir,
        dry_run=args.dry_run,
    )

    oversized_count = len(prepared) + len(failed)
    if args.dry_run:
        oversized_count = sum(
            path.stat().st_size > MAX_TELEGRAM_VIDEO_BYTES for path in videos
        )

    print("\nИтог:")
    print(f"  Видео всего: {len(videos)}")
    print(f"  Уже подходят: {len(skipped)}")
    print(f"  Крупных: {oversized_count}")
    if not args.dry_run:
        print(f"  Подготовлено: {len(prepared)}")
        print(f"  Ошибок: {len(failed)}")

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
