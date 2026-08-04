from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from aiogram.types import InlineKeyboardButton


class ButtonStyleAlias(StrEnum):
    """Stable aliases shared by the visual builder and the bot runtime."""

    DEFAULT = "default"
    PRIMARY = "primary"
    SUCCESS = "success"
    DANGER = "danger"


def normalize_style(value: str | ButtonStyleAlias | None) -> ButtonStyleAlias:
    if value is None or value == "":
        return ButtonStyleAlias.DEFAULT
    try:
        return ButtonStyleAlias(str(value).lower())
    except ValueError as exc:
        allowed = ", ".join(style.value for style in ButtonStyleAlias)
        raise ValueError(f"Unknown button style {value!r}. Allowed: {allowed}") from exc


def callback_button(
    *,
    text: str,
    callback_data: str,
    style: str | ButtonStyleAlias | None = ButtonStyleAlias.DEFAULT,
) -> InlineKeyboardButton:
    """Build a Telegram button while keeping schema-only imports lightweight."""
    from aiogram.enums import ButtonStyle
    from aiogram.types import InlineKeyboardButton

    alias = normalize_style(style)
    style_map = {
        ButtonStyleAlias.DEFAULT: None,
        ButtonStyleAlias.PRIMARY: ButtonStyle.PRIMARY,
        ButtonStyleAlias.SUCCESS: ButtonStyle.SUCCESS,
        ButtonStyleAlias.DANGER: ButtonStyle.DANGER,
    }
    return InlineKeyboardButton(
        text=text,
        callback_data=callback_data,
        style=style_map[alias],
    )
