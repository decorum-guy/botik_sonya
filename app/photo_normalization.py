from __future__ import annotations

import logging
import math
from io import BytesIO
from pathlib import Path
from typing import Any

from aiogram.types import BufferedInputFile
from PIL import Image, ImageOps, UnidentifiedImageError
from pillow_heif import register_heif_opener

logger = logging.getLogger(__name__)

# Telegram accepts photos up to 10 MB, with width + height <= 10,000 and
# an aspect ratio no greater than 20. Leave a little safety margin so the
# normalized JPEG is reliably accepted after multipart upload.
MAX_TELEGRAM_PHOTO_BYTES = 9_500_000
MAX_TELEGRAM_DIMENSION_SUM = 9_000
MAX_TELEGRAM_ASPECT_RATIO = 20.0
JPEG_QUALITIES = (92, 86, 80, 74, 68)

register_heif_opener()


def _flatten_to_rgb(image: Image.Image) -> Image.Image:
    if image.mode in {"RGBA", "LA"} or "transparency" in image.info:
        rgba = image.convert("RGBA")
        background = Image.new("RGB", rgba.size, "white")
        background.paste(rgba, mask=rgba.getchannel("A"))
        return background
    return image.convert("RGB")


def _fit_telegram_geometry(image: Image.Image) -> Image.Image:
    width, height = image.size
    if width <= 0 or height <= 0:
        raise ValueError("image has invalid dimensions")

    ratio = max(width, height) / min(width, height)
    if ratio > MAX_TELEGRAM_ASPECT_RATIO:
        if width > height:
            target_height = math.ceil(width / MAX_TELEGRAM_ASPECT_RATIO)
            canvas = Image.new("RGB", (width, target_height), "white")
            canvas.paste(image, (0, (target_height - height) // 2))
        else:
            target_width = math.ceil(height / MAX_TELEGRAM_ASPECT_RATIO)
            canvas = Image.new("RGB", (target_width, height), "white")
            canvas.paste(image, ((target_width - width) // 2, 0))
        image = canvas
        width, height = image.size

    dimension_sum = width + height
    if dimension_sum > MAX_TELEGRAM_DIMENSION_SUM:
        scale = MAX_TELEGRAM_DIMENSION_SUM / dimension_sum
        image = image.resize(
            (max(1, round(width * scale)), max(1, round(height * scale))),
            Image.Resampling.LANCZOS,
        )

    return image


def _encode_jpeg(image: Image.Image, quality: int) -> bytes:
    buffer = BytesIO()
    image.save(
        buffer,
        format="JPEG",
        quality=quality,
        optimize=True,
        progressive=False,
        subsampling=2,
    )
    return buffer.getvalue()


def normalize_photo_bytes(path: Path) -> bytes:
    try:
        with Image.open(path) as opened:
            opened.seek(0)
            opened.load()
            image = ImageOps.exif_transpose(opened).copy()
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise ValueError(
            f"Не удалось прочитать изображение {path}. "
            "Файл повреждён либо имеет неподдерживаемый формат."
        ) from exc

    image = _flatten_to_rgb(image)
    image = _fit_telegram_geometry(image)

    for quality in JPEG_QUALITIES:
        payload = _encode_jpeg(image, quality)
        if len(payload) <= MAX_TELEGRAM_PHOTO_BYTES:
            return payload

    # Extremely noisy high-resolution images can still exceed the limit at a
    # low JPEG quality. Shrink them gradually instead of failing the quest.
    for _ in range(6):
        width, height = image.size
        image = image.resize(
            (max(1, round(width * 0.85)), max(1, round(height * 0.85))),
            Image.Resampling.LANCZOS,
        )
        payload = _encode_jpeg(image, JPEG_QUALITIES[-1])
        if len(payload) <= MAX_TELEGRAM_PHOTO_BYTES:
            return payload

    raise ValueError(
        f"Изображение {path} не удалось уменьшить до допустимого размера Telegram."
    )


def install_photo_normalization(engine_module: Any) -> None:
    engine_class = engine_module.QuestEngine
    if getattr(engine_class, "_photo_normalization_installed", False):
        return

    original_send_media = engine_class._send_media

    async def _send_media(self, chat_id: int, action) -> None:
        if action.type != "send_photo":
            await original_send_media(self, chat_id, action)
            return

        path = self._safe_media_path(action.path)
        payload = normalize_photo_bytes(path)
        file = BufferedInputFile(payload, filename=f"{path.stem}.jpg")
        kwargs = {
            "chat_id": chat_id,
            "caption": action.caption or None,
            "parse_mode": engine_module.parse_mode(action.parse_mode),
            "disable_notification": action.disable_notification,
        }
        logger.info(
            "Normalized photo %s for Telegram: %.1f KB",
            action.path,
            len(payload) / 1024,
        )
        await self.bot.send_photo(photo=file, **kwargs)

    engine_class._send_media = _send_media
    engine_class._photo_normalization_installed = True
