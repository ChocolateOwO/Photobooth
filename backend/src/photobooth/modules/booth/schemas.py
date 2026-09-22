"""Booth API schemas (participant-safe: no files, storage or frame origin)."""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from photobooth.modules.booth.domain import BoothFrame, FrameMenu, FramePlan, StartScreen

FrameIdField = Annotated[
    str, Field(pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
]


class FramePlanResponse(BaseModel):
    frame_id: str
    template_key: str
    layout_label: str = Field(examples=["2\u00d76"])
    captures: int = Field(description="Photos taken in the session")
    outputs: int = Field(description="Prints/strips made from them")
    photos_per_output: int
    output_capture_groups: list[list[int]]
    output_label: str | None = Field(description="e.g. '2 strips'; null for a single output")

    @classmethod
    def of(cls, plan: FramePlan) -> FramePlanResponse:
        return cls(
            frame_id=plan.frame_id,
            template_key=plan.template_key,
            layout_label=plan.layout_label,
            captures=plan.captures,
            outputs=plan.outputs,
            photos_per_output=plan.photos_per_output,
            output_capture_groups=[list(group) for group in plan.output_capture_groups],
            output_label=plan.output_label,
        )


class BoothFrameResponse(BaseModel):
    id: str
    name: str
    preview_url: str
    plan: FramePlanResponse

    @classmethod
    def of(cls, frame: BoothFrame) -> BoothFrameResponse:
        return cls(
            id=frame.frame_id,
            name=frame.name,
            preview_url=f"/api/booth/frames/{frame.frame_id}/preview.jpg?v={frame.version}",
            plan=FramePlanResponse.of(frame.plan),
        )


class StartScreenResponse(BaseModel):
    """Presentation data of the participant start screen, nothing else."""

    start_button_text: str
    logo_url: str | None = Field(description="The event logo, or null for the neutral mark")
    background_url: str | None = Field(description="The event background, or null for none")

    @classmethod
    def of(cls, screen: StartScreen) -> StartScreenResponse:
        def url(kind: str, version: str | None) -> str | None:
            return None if version is None else f"/api/booth/start/{kind}?v={version}"

        return cls(
            start_button_text=screen.start_text,
            logo_url=url("logo", screen.logo_version),
            background_url=url("background", screen.background_version),
        )


class FrameMenuResponse(BaseModel):
    frames: list[BoothFrameResponse] = Field(description="Offered frames in display order")
    layouts: list[str] = Field(description="Layouts with at least one offered frame")
    allow_surprise_me: bool
    theme: dict[str, str] = Field(description="Event theme tokens for the participant screens")
    start_screen: StartScreenResponse

    @classmethod
    def of(cls, menu: FrameMenu) -> FrameMenuResponse:
        return cls(
            frames=[BoothFrameResponse.of(frame) for frame in menu.frames],
            layouts=menu.layouts,
            allow_surprise_me=menu.allow_surprise_me,
            theme=dict(menu.theme_tokens),
            start_screen=StartScreenResponse.of(menu.start_screen),
        )


class FrameChoiceBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    frame_id: FrameIdField
