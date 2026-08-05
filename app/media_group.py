from __future__ import annotations

from dataclasses import dataclass

MEDIA_GROUP_PREFIX = "album:v1"
MIN_MEDIA_GROUP_ITEMS = 2
MAX_MEDIA_GROUP_ITEMS = 6


@dataclass(frozen=True)
class MediaGroupItem:
    kind: str
    path: str


def is_media_group_path(value: str) -> bool:
    return value.replace("\r\n", "\n").startswith(f"{MEDIA_GROUP_PREFIX}\n")


def _safe_relative_path(value: str) -> str:
    normalized = value.replace("\\", "/").strip()
    if not normalized or normalized.startswith(("/", "~")) or ".." in normalized.split("/"):
        raise ValueError("Media path must be a safe repository-relative path")
    return normalized


def parse_media_group_path(value: str) -> list[MediaGroupItem]:
    normalized = value.replace("\r\n", "\n").strip()
    lines = normalized.split("\n")
    if not lines or lines[0] != MEDIA_GROUP_PREFIX:
        raise ValueError("Media group path must start with album:v1")

    items: list[MediaGroupItem] = []
    for line_number, line in enumerate(lines[1:], start=2):
        if not line.strip():
            continue
        try:
            kind, path = line.split("\t", 1)
        except ValueError as exc:
            raise ValueError(
                f"Media group line {line_number} must use '<photo|video>\\t<path>'"
            ) from exc
        kind = kind.strip().lower()
        if kind not in {"photo", "video"}:
            raise ValueError(f"Media group line {line_number} has unsupported type: {kind}")
        items.append(MediaGroupItem(kind=kind, path=_safe_relative_path(path)))

    if not MIN_MEDIA_GROUP_ITEMS <= len(items) <= MAX_MEDIA_GROUP_ITEMS:
        raise ValueError(
            f"Media group must contain {MIN_MEDIA_GROUP_ITEMS}-{MAX_MEDIA_GROUP_ITEMS} items"
        )
    return items


def encode_media_group_path(items: list[MediaGroupItem]) -> str:
    if not MIN_MEDIA_GROUP_ITEMS <= len(items) <= MAX_MEDIA_GROUP_ITEMS:
        raise ValueError(
            f"Media group must contain {MIN_MEDIA_GROUP_ITEMS}-{MAX_MEDIA_GROUP_ITEMS} items"
        )
    lines = [MEDIA_GROUP_PREFIX]
    lines.extend(f"{item.kind}\t{_safe_relative_path(item.path)}" for item in items)
    return "\n".join(lines)
