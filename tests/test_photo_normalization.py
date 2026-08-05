from __future__ import annotations

from io import BytesIO

from PIL import Image

from app.photo_normalization import (
    MAX_TELEGRAM_ASPECT_RATIO,
    MAX_TELEGRAM_DIMENSION_SUM,
    normalize_photo_bytes,
)


def test_normalize_photo_converts_transparency_to_rgb_jpeg(tmp_path) -> None:
    source = tmp_path / "transparent.png"
    Image.new("RGBA", (320, 240), (255, 0, 0, 128)).save(source)

    payload = normalize_photo_bytes(source)

    with Image.open(BytesIO(payload)) as normalized:
        assert normalized.format == "JPEG"
        assert normalized.mode == "RGB"
        assert normalized.size == (320, 240)


def test_normalize_photo_fits_telegram_geometry(tmp_path) -> None:
    source = tmp_path / "panorama.png"
    Image.new("RGB", (4000, 100), "black").save(source)

    payload = normalize_photo_bytes(source)

    with Image.open(BytesIO(payload)) as normalized:
        width, height = normalized.size
        assert width + height <= MAX_TELEGRAM_DIMENSION_SUM
        assert max(width, height) / min(width, height) <= MAX_TELEGRAM_ASPECT_RATIO
