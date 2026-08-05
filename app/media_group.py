from __future__ import annotations

import json
import re
from dataclasses import dataclass
from urllib.parse import quote, unquote

MEDIA_GROUP_PREFIX = "album:v2:"
LEGACY_MEDIA_GROUP_PREFIX = "album:v1"
MIN_MEDIA_GROUP_ITEMS = 2
MAX_MEDIA_GROUP_ITEMS = 6


@dataclass(frozen=True)
class MediaGroupItem:
    kind: str
    path: str


def is_media_group_path(value: str) -> bool:
    normalized = value.replace("\r\n", "\n").strip()
    return normalized.startswith(MEDIA_GROUP_PREFIX) or normalized.startswith(
        LEGACY_MEDIA_GROUP_PREFIX
    )


def _safe_relative_path(value: str) -> str:
    normalized = value.replace("\\", "/").strip()
    if not normalized or normalized.startswith(("/", "~")) or ".." in normalized.split("/"):
        raise ValueError("Media path must be a safe repository-relative path")
    return normalized


def _validated_items(raw_items: object) -> list[MediaGroupItem]:
    if not isinstance(raw_items, list):
        raise ValueError("Media group payload must be a list")

    items: list[MediaGroupItem] = []
    for index, raw in enumerate(raw_items, start=1):
        if not isinstance(raw, dict):
            raise ValueError(f"Media group item {index} must be an object")
        kind = str(raw.get("kind", "")).strip().lower()
        if kind not in {"photo", "video"}:
            raise ValueError(f"Media group item {index} has unsupported type: {kind}")
        items.append(
            MediaGroupItem(
                kind=kind,
                path=_safe_relative_path(str(raw.get("path", ""))),
            )
        )

    if not MIN_MEDIA_GROUP_ITEMS <= len(items) <= MAX_MEDIA_GROUP_ITEMS:
        raise ValueError(
            f"Media group must contain {MIN_MEDIA_GROUP_ITEMS}-{MAX_MEDIA_GROUP_ITEMS} items"
        )
    return items


def _parse_v2(value: str) -> list[MediaGroupItem]:
    payload = value[len(MEDIA_GROUP_PREFIX) :]
    if not payload:
        raise ValueError("Media group payload is empty")
    try:
        decoded = json.loads(unquote(payload))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError("Media group payload is not valid JSON") from exc
    return _validated_items(decoded)


def _parse_legacy_lines(value: str) -> list[MediaGroupItem]:
    lines = value.split("\n")
    raw_items: list[dict[str, str]] = []
    for line_number, line in enumerate(lines[1:], start=2):
        if not line.strip():
            continue
        try:
            kind, path = line.split("\t", 1)
        except ValueError as exc:
            raise ValueError(
                f"Media group line {line_number} must use '<photo|video>\\t<path>'"
            ) from exc
        raw_items.append({"kind": kind, "path": path})
    return _validated_items(raw_items)


def _parse_compacted_legacy(value: str) -> list[MediaGroupItem]:
    """Recover v1 values flattened by an HTML text input.

    Browsers strip newlines from ``input[type=text]`` values. The first builder
    implementation therefore turned ``album:v1\nphoto\tmedia/...`` into one
    concatenated line. Accept that exact legacy shape so existing local drafts
    can be migrated instead of being lost.
    """

    remainder = value[len(LEGACY_MEDIA_GROUP_PREFIX) :].strip()
    pattern = re.compile(
        r"(photo|video)\s+(media/.+?)(?=(?:photo|video)\s+media/|$)",
        re.IGNORECASE,
    )
    raw_items = [
        {"kind": match.group(1), "path": match.group(2)}
        for match in pattern.finditer(remainder)
    ]
    if not raw_items:
        raise ValueError("Compacted legacy media group could not be decoded")
    return _validated_items(raw_items)


def parse_media_group_path(value: str) -> list[MediaGroupItem]:
    normalized = value.replace("\r\n", "\n").strip()
    if normalized.startswith(MEDIA_GROUP_PREFIX):
        return _parse_v2(normalized)
    if normalized == LEGACY_MEDIA_GROUP_PREFIX or normalized.startswith(
        f"{LEGACY_MEDIA_GROUP_PREFIX}\n"
    ):
        return _parse_legacy_lines(normalized)
    if normalized.startswith(LEGACY_MEDIA_GROUP_PREFIX):
        return _parse_compacted_legacy(normalized)
    raise ValueError("Media group path must start with album:v2: or album:v1")


def encode_media_group_path(items: list[MediaGroupItem]) -> str:
    validated = _validated_items(
        [{"kind": item.kind, "path": item.path} for item in items]
    )
    payload = json.dumps(
        [{"kind": item.kind, "path": item.path} for item in validated],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return f"{MEDIA_GROUP_PREFIX}{quote(payload, safe='')}"
