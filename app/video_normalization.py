from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from aiogram.types import FSInputFile

logger = logging.getLogger(__name__)

# Cloud Bot API accepts multipart video uploads up to 50 MB. Keep generous
# headroom for multipart overhead and small encoder variance.
MAX_TELEGRAM_VIDEO_BYTES = 49_000_000
TARGET_VIDEO_BYTES = 43_000_000
AUDIO_BITRATE = 96_000
CACHE_VERSION = "telegram-video-v1"
VIDEO_FILTER = (
    "scale=1440:1440:force_original_aspect_ratio=decrease:"
    "force_divisible_by=2"
)


def _require_binary(name: str) -> str:
    binary = shutil.which(name)
    if binary is None:
        raise RuntimeError(
            f"Для автоматического пережатия видео требуется `{name}`. "
            "Установи ffmpeg через `brew install ffmpeg` и перезапусти бота."
        )
    return binary


def probe_video_duration(path: Path) -> float:
    ffprobe = _require_binary("ffprobe")
    result = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "json",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    try:
        duration = float(json.loads(result.stdout)["format"]["duration"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError(f"Не удалось определить длительность видео {path}.") from exc
    if duration <= 0:
        raise ValueError(f"Видео {path} имеет некорректную длительность.")
    return duration


def target_video_bitrate(duration_seconds: float, target_bytes: int = TARGET_VIDEO_BYTES) -> int:
    # Reserve 2% for container overhead, then subtract the AAC stream.
    total_bits_per_second = target_bytes * 8 * 0.98 / duration_seconds
    return max(250_000, int(total_bits_per_second - AUDIO_BITRATE))


def _cache_path(path: Path, cache_dir: Path) -> Path:
    stat = path.stat()
    identity = (
        f"{CACHE_VERSION}|{path.resolve()}|{stat.st_size}|{stat.st_mtime_ns}"
    ).encode()
    digest = hashlib.sha256(identity).hexdigest()[:20]
    return cache_dir / f"{path.stem}-{digest}.mp4"


def _run_ffmpeg(command: list[str], path: Path) -> None:
    try:
        subprocess.run(command, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as exc:
        details = (exc.stderr or exc.stdout or "").strip()
        tail = "\n".join(details.splitlines()[-12:])
        raise RuntimeError(
            f"ffmpeg не смог подготовить видео {path}.\n{tail}"
        ) from exc


def _encode_two_pass(
    source: Path,
    destination: Path,
    bitrate: int,
    passlog: Path,
) -> None:
    ffmpeg = _require_binary("ffmpeg")
    common = [
        ffmpeg,
        "-y",
        "-i",
        str(source),
        "-map",
        "0:v:0",
        "-vf",
        VIDEO_FILTER,
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-b:v",
        str(bitrate),
        "-pix_fmt",
        "yuv420p",
        "-passlogfile",
        str(passlog),
    ]

    _run_ffmpeg(
        common
        + [
            "-pass",
            "1",
            "-an",
            "-sn",
            "-f",
            "null",
            os.devnull,
        ],
        source,
    )
    _run_ffmpeg(
        common
        + [
            "-pass",
            "2",
            "-map",
            "0:a?",
            "-c:a",
            "aac",
            "-b:a",
            str(AUDIO_BITRATE),
            "-sn",
            "-movflags",
            "+faststart",
            str(destination),
        ],
        source,
    )


def prepare_video_for_telegram(path: Path, cache_dir: Path) -> Path:
    size = path.stat().st_size
    if size <= MAX_TELEGRAM_VIDEO_BYTES:
        return path

    cache_dir.mkdir(parents=True, exist_ok=True)
    cached = _cache_path(path, cache_dir)
    if cached.is_file() and cached.stat().st_size <= MAX_TELEGRAM_VIDEO_BYTES:
        return cached

    duration = probe_video_duration(path)
    base_bitrate = target_video_bitrate(duration)
    temporary = cached.with_suffix(".tmp.mp4")
    passlog = cache_dir / f".{cached.stem}-pass"

    try:
        for attempt, factor in enumerate((1.0, 0.82), start=1):
            temporary.unlink(missing_ok=True)
            bitrate = max(250_000, int(base_bitrate * factor))
            logger.info(
                "Compressing video %s for Telegram (attempt %s, %.2f Mbps)",
                path,
                attempt,
                bitrate / 1_000_000,
            )
            _encode_two_pass(path, temporary, bitrate, passlog)
            if temporary.stat().st_size <= MAX_TELEGRAM_VIDEO_BYTES:
                temporary.replace(cached)
                logger.info(
                    "Prepared Telegram video %s: %.1f MB -> %.1f MB",
                    path,
                    size / 1_000_000,
                    cached.stat().st_size / 1_000_000,
                )
                return cached

        raise RuntimeError(
            f"Видео {path} не удалось уменьшить ниже лимита Telegram после двух попыток."
        )
    finally:
        temporary.unlink(missing_ok=True)
        for extra in cache_dir.glob(f"{passlog.name}*"):
            extra.unlink(missing_ok=True)


def install_video_normalization(engine_module: Any) -> None:
    engine_class = engine_module.QuestEngine
    if getattr(engine_class, "_video_normalization_installed", False):
        return

    original_send_media = engine_class._send_media

    async def _send_media(self, chat_id: int, action) -> None:
        if action.type != "send_video":
            await original_send_media(self, chat_id, action)
            return

        source = self._safe_media_path(action.path)
        prepared = await asyncio.to_thread(
            prepare_video_for_telegram,
            source,
            self.root / ".cache" / "telegram_media",
        )
        file = FSInputFile(prepared)
        kwargs = {
            "chat_id": chat_id,
            "caption": action.caption or None,
            "parse_mode": engine_module.parse_mode(action.parse_mode),
            "disable_notification": action.disable_notification,
        }
        await self.bot.send_video(video=file, supports_streaming=True, **kwargs)

    engine_class._send_media = _send_media
    engine_class._video_normalization_installed = True
