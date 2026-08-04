from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.button_styles import ButtonStyleAlias


ParseModeName = Literal["HTML", "MarkdownV2", "none"]
TextDeliveryMode = Literal["instant", "characters", "words"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RoadmapMeta(StrictModel):
    version: int = 1
    title: str = "Квест"
    entry_step_id: str
    intro_step_id: str | None = None


class BaseAction(StrictModel):
    type: str


class StreamSegment(StrictModel):
    text: str
    pause_after_seconds: float = Field(default=0, ge=0, le=60)


class SendTextAction(BaseAction):
    type: Literal["send_text"]
    text: str
    parse_mode: ParseModeName = "HTML"
    disable_notification: bool = False
    delivery_mode: TextDeliveryMode = "instant"
    typing_speed_seconds: float = Field(default=0.12, ge=0.03, le=5)
    stream_segments: list[StreamSegment] = Field(default_factory=list)


class MediaAction(BaseAction):
    type: Literal["send_photo", "send_video", "send_audio", "send_document"]
    path: str
    caption: str = ""
    parse_mode: ParseModeName = "HTML"
    disable_notification: bool = False

    @field_validator("path")
    @classmethod
    def safe_relative_path(cls, value: str) -> str:
        normalized = value.replace("\\", "/").strip()
        if not normalized or normalized.startswith(("/", "~")) or ".." in normalized.split("/"):
            raise ValueError("Media path must be a safe repository-relative path")
        return normalized


class DelayAction(BaseAction):
    type: Literal["delay"]
    seconds: float = Field(ge=0, le=3600)


class MemoryAction(BaseAction):
    type: Literal["memory_reconstruction"]
    memory_id: str
    number: int = Field(ge=1)
    total: int = Field(ge=1)
    date_text: str
    title: str = "ВОССТАНОВЛЕНИЕ ВОСПОМИНАНИЯ"
    intro: str = ""
    outro: str = ""
    message_delay_seconds: float = Field(default=0.65, ge=0, le=10)


class ValidatorSpec(StrictModel):
    type: Literal[
        "any",
        "text_exact",
        "text_contains",
        "regex",
        "integer_equal",
        "integer_range",
        "date_equal",
    ] = "any"
    values: list[str] = Field(default_factory=list)
    pattern: str = ""
    number: int | None = None
    minimum: int | None = None
    maximum: int | None = None
    date: str = ""
    case_sensitive: bool = False
    trim: bool = True
    replace_yo: bool = True
    remove_punctuation: bool = True

    @model_validator(mode="after")
    def validate_payload(self) -> "ValidatorSpec":
        if self.type in {"text_exact", "text_contains"} and not self.values:
            raise ValueError(f"Validator {self.type} requires non-empty values")
        if self.type == "regex" and not self.pattern:
            raise ValueError("Regex validator requires pattern")
        if self.type == "integer_equal" and self.number is None:
            raise ValueError("integer_equal requires number")
        if self.type == "integer_range":
            if self.minimum is None or self.maximum is None:
                raise ValueError("integer_range requires minimum and maximum")
            if self.minimum > self.maximum:
                raise ValueError("minimum must be <= maximum")
        if self.type == "date_equal" and not self.date:
            raise ValueError("date_equal requires date in YYYY-MM-DD format")
        return self


class AskInputAction(BaseAction):
    type: Literal["ask_input"]
    prompt: str = ""
    parse_mode: ParseModeName = "HTML"
    validator: ValidatorSpec
    wrong_answers: list[str] = Field(default_factory=lambda: ["Пока не совпало. Попробуй ещё раз."])
    success_text: str = ""
    next_step: str | None = None


class ButtonSpec(StrictModel):
    text: str
    id: str
    style: ButtonStyleAlias = ButtonStyleAlias.DEFAULT
    next_step: str | None = None
    answer_text: str = ""
    callback_text: str = Field(default="Принято", min_length=1, max_length=200)


class ButtonsAction(BaseAction):
    type: Literal["buttons"]
    text: str
    parse_mode: ParseModeName = "HTML"
    columns: int = Field(default=1, ge=1, le=4)
    buttons: list[ButtonSpec] = Field(min_length=1)


class GotoAction(BaseAction):
    type: Literal["goto"]
    step_id: str


Action = Annotated[
    SendTextAction
    | MediaAction
    | DelayAction
    | MemoryAction
    | AskInputAction
    | ButtonsAction
    | GotoAction,
    Field(discriminator="type"),
]


class RoadmapStep(StrictModel):
    id: str
    title: str
    notes: str = ""
    actions: list[Action] = Field(default_factory=list)


class Roadmap(StrictModel):
    meta: RoadmapMeta
    steps: list[RoadmapStep]

    @model_validator(mode="after")
    def validate_graph(self) -> "Roadmap":
        ids = [step.id for step in self.steps]
        if len(ids) != len(set(ids)):
            raise ValueError("Step IDs must be unique")
        known = set(ids)
        if self.meta.entry_step_id not in known:
            raise ValueError("meta.entry_step_id does not exist")
        if self.meta.intro_step_id and self.meta.intro_step_id not in known:
            raise ValueError("meta.intro_step_id does not exist")
        for step in self.steps:
            for action in step.actions:
                targets: list[str] = []
                if isinstance(action, AskInputAction) and action.next_step:
                    targets.append(action.next_step)
                elif isinstance(action, GotoAction):
                    targets.append(action.step_id)
                elif isinstance(action, ButtonsAction):
                    targets.extend(button.next_step for button in action.buttons if button.next_step)
                missing = [target for target in targets if target not in known]
                if missing:
                    raise ValueError(f"Step {step.id} references missing step(s): {missing}")
        return self

    def step(self, step_id: str) -> RoadmapStep:
        for step in self.steps:
            if step.id == step_id:
                return step
        raise KeyError(step_id)
