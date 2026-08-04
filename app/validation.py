from __future__ import annotations

import re
import string
from datetime import datetime

from app.models import ValidatorSpec


_PUNCTUATION_TABLE = str.maketrans("", "", string.punctuation + "«»„“”’‘—–…")


def normalize_text(value: str, spec: ValidatorSpec) -> str:
    result = value
    if spec.trim:
        result = result.strip()
    if spec.replace_yo:
        result = result.replace("Ё", "Е").replace("ё", "е")
    if not spec.case_sensitive:
        result = result.casefold()
    if spec.remove_punctuation:
        result = result.translate(_PUNCTUATION_TABLE)
    return " ".join(result.split())


def validate_answer(raw: str, spec: ValidatorSpec) -> bool:
    if spec.type == "any":
        return bool(raw.strip())

    value = normalize_text(raw, spec)

    if spec.type == "text_exact":
        return value in {normalize_text(item, spec) for item in spec.values}
    if spec.type == "text_contains":
        return any(normalize_text(item, spec) in value for item in spec.values)
    if spec.type == "regex":
        flags = 0 if spec.case_sensitive else re.IGNORECASE
        return re.fullmatch(spec.pattern, raw.strip(), flags=flags) is not None
    if spec.type == "integer_equal":
        try:
            return int(raw.strip()) == spec.number
        except ValueError:
            return False
    if spec.type == "integer_range":
        try:
            number = int(raw.strip())
        except ValueError:
            return False
        return spec.minimum <= number <= spec.maximum  # type: ignore[operator]
    if spec.type == "date_equal":
        parsed = _parse_date(raw)
        expected = datetime.strptime(spec.date, "%Y-%m-%d").date()
        return parsed == expected
    return False


def _parse_date(value: str):
    cleaned = value.strip().replace("/", ".").replace("-", ".")
    for fmt in ("%d.%m.%Y", "%d.%m.%y", "%Y.%m.%d"):
        try:
            return datetime.strptime(cleaned, fmt).date()
        except ValueError:
            continue
    return None
