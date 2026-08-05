from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from aiogram.types import FSInputFile

logger = logging.getLogger(__name__)

# Cloud Bot API accepts multipart video uploads up to 50 MB. Files below this
# threshold must be uploaded byte-for-byte without touching FFmpeg.
MAX_TELEGRAM_VIDEO_BYTES = 49_000_000
TARGET_VIDEO_BYTES = 43_000_000
AUDIO_BITRATE = 96_000
CACHE_VERSION = "telegram-video-v2"
CACHE_FINGERPRINT_CHUNK_BYTES = 1_048_576

# Preserve the source aspect ratio explicitly. Portrait stays portrait,
# landscape stays landscape, square stays square. setsar=1 prevents odd sample
# aspect-ratio metadata from changing the displayed geometry in Telegram.
VIDEO_FILTER = (
    "scale=w='if(gte(iw,ih),min(iw,1440),-2)':"
    "h='if(lt(iw,ih),min(ih,1440),-2)',setsar=1"
)


@dataclass(frozen=True, slots=True)
class VideoMetadata:
    width: int
    height: int
    duration: int


def _require_binary(name: str) -> str:
    binary = shutil.which(name)
    if binary is None:
        raise RuntimeError(
            f"Для автоматического пережатия видео требуется `{name}`. "
            "Установи ffmpeg через `brew install ffmpeg` и перезапусти бота."
        )
    return binary


def _ffprobe_payload(path: Path) -> dict[str, Any]:
    ffprobe = _require_binary("ffprobe")
    result = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_streams",
            "-show_format",
            "-of",
            "json",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ValueError(f"ffprobe вернул некорректные данные для {path}.") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"ffprobe не смог прочитать видео {path}.")
    return payload


def _stream_rotation(stream: dict[str, Any]) -> int:
    candidates: list[Any] = []
    tags = stream.get("tags")
    if isinstance(tags, dict):
        candidates.append(tags.get("rotate"))
    side_data = stream.get("side_data_list")
    if isinstance(side_data, list):
        for item in side_data:
            if isinstance(item, dict):
                candidates.append(item.get("rotation"))

    for value in candidates:
        if value is None:
            continue
        try:
            return int(round(float(value))) % 360
        except (TypeError, ValueError):
            continue
    return 0


def probe_video_metadata(path: Path) -> VideoMetadata:
    """Read display geometry, including CapCut/iPhone rotation metadata."""

    payload = _ffprobe_payload(path)
    streams = payload.get("streams")
    if not isinstance(streams, list) or not streams or not isinstance(streams[0], dict):
        raise ValueError(f"В файле {path} не найден видеопоток.")
    stream = streams[0]

    try:
        width = int(stream["width"])
        height = int(stream["height"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"Не удалось определить размеры видео {path}.") from exc
    if width <= 0 or height <= 0:
        raise ValueError(f"Видео {path} имеет некорректные размеры.")

    # Some editors store a landscape coded frame plus rotate=90 instead of a
    # genuinely portrait frame. Telegram accepts sender-defined display width
    # and height, so pass the dimensions after applying that rotation.
    if _stream_rotation(stream) in {90, 270}:
        width, height = height, width

    format_data = payload.get("format")
    try:
        duration_value = float(format_data["duration"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"Не удалось определить длительность видео {path}.") from exc
    if duration_value <= 0:
        raise ValueError(f"Видео {path} имеет некорректную длительность.")

    return VideoMetadata(
        width=width,
        height=height,
        duration=max(1, math.ceil(duration_value)),
    )


def safe_video_metadata(path: Path) -> VideoMetadata | None:
    try:
        return probe_video_metadata(path)
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
        logger.warning(
            "Could not read video metadata for %s; Telegram will inspect it: %s",
            path,
            exc,
        )
        return None


def probe_video_duration(path: Path) -> float:
    payload = _ffprobe_payload(path)
    format_data = payload.get("format")
    try:
        duration = float(format_data["duration"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"Не удалось определить длительность видео {path}.") from exc
    if duration <= 0:
        raise ValueError(f"Видео {path} имеет некорректную длительность.")
    return duration


def target_video_bitrate(duration_seconds: float, target_bytes: int = TARGET_VIDEO_BYTES) -> int:
    # Reserve 2% for container overhead, then subtract the AAC stream.
    total_bits_per_second = target_bytes * 8 * 0.98 / duration_seconds
    return max(250_000, int(total_bits_per_second - AUDIO_BITRATE))


def _content_fingerprint(path: Path) -> str:
    """Build a cache identity that survives moving the project to a server."""

    stat = path.stat()
    digest = hashlib.sha256()
    digest.update(CACHE_VERSION.encode())
    digest.update(str(stat.st_size).encode())
    digest.update(str(stat.st_mtime_ns).encode())

    with path.open("rb") as handle:
        digest.update(handle.read(CACHE_FINGERPRINT_CHUNK_BYTES))
        if stat.st_size > CACHE_FINGERPRINT_CHUNK_BYTES:
            handle.seek(max(CACHE_FINGERPRINT_CHUNK_BYTES, stat.st_size - CACHE_FINGERPRINT_CHUNK_BYTES))
            digest.update(handle.read(CACHE_FINGERPRINT_CHUNK_BYTES))

    return digest.hexdigest()[:20]


def _cache_path(path: Path, cache_dir: Path) -> Path:
    return cache_dir / f"{path.stem}-{_content_fingerprint(path)}.mp4"


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
            "-map_metadata",
            "-1",
            "-metadata:s:v:0",
            "rotate=0",
            "-movflags",
            "+faststart",
            str(destination),
        ],
        source,
    )


def prepare_video_for_telegram(path: Path, cache_dir: Path) -> Path:
    size = path.stat().st_size
    if size <= MAX_TELEGRAM_VIDEO_BYTES:
        logger.info(
            "Using original video without re-encoding: %s (%.2f MB)",
            path,
            size / 1_000_000,
        )
        return path

    cache_dir.mkdir(parents=True, exist_ok=True)
    cached = _cache_path(path, cache_dir)
    if cached.is_file() and cached.stat().st_size <= MAX_TELEGRAM_VIDEO_BYTES:
        logger.info(
            "Using prepared video cache: %s -> %s (%.2f MB)",
            path,
            cached,
            cached.stat().st_size / 1_000_000,
        )
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


def video_send_kwargs(path: Path) -> dict[str, int]:
    metadata = safe_video_metadata(path)
    if metadata is None:
        return {}
    return {
        "width": metadata.width,
        "height": metadata.height,
        "duration": metadata.duration,
    }


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
        metadata_kwargs = await asyncio.to_thread(video_send_kwargs, prepared)
        file = FSInputFile(prepared)
        kwargs = {
            "chat_id": chat_id,
            "caption": action.caption or None,
            "parse_mode": engine_module.parse_mode(action.parse_mode),
            "disable_notification": action.disable_notification,
            **metadata_kwargs,
        }
        logger.info(
            "Sending video %s as %s with geometry %sx%s",
            source,
            prepared,
            metadata_kwargs.get("width", "auto"),
            metadata_kwargs.get("height", "auto"),
        )
        await self.bot.send_video(video=file, supports_streaming=True, **kwargs)

    engine_class._send_media = _send_media
    engine_class._video_normalization_installed = True
