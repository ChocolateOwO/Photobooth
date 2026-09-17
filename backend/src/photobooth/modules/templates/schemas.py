"""Public API contracts for photo templates."""

from __future__ import annotations

from pydantic import BaseModel

from photobooth.modules.templates.domain import PhotoTemplate, Rect


class RectModel(BaseModel):
    x: int
    y: int
    w: int
    h: int

    @classmethod
    def of(cls, rect: Rect) -> RectModel:
        return cls(x=rect.x, y=rect.y, w=rect.w, h=rect.h)


class SlotModel(RectModel):
    index: int
    fit: str
    anchor: str
    aspect: str


class FrameRulesModel(BaseModel):
    format: str
    mode: str
    exact_size: bool
    max_bytes: int
    color: str
    slot_min_transparency: float
    animated: bool


class TemplateLinks(BaseModel):
    spec: str
    blank_png: str
    guide_png: str
    sample_jpgs: list[str]


class TemplateSummary(BaseModel):
    key: str
    version: int
    name: str
    width_in: float
    height_in: float
    dpi: int
    width_px: int
    height_px: int
    orientation: str
    photos_per_output: int
    captures_per_session: int
    outputs_per_session: int
    links: TemplateLinks

    @classmethod
    def of(cls, t: PhotoTemplate) -> TemplateSummary:
        base = f"/api/templates/{t.key}"
        query = f"?version={t.version}"
        return cls(
            key=t.key,
            version=t.version,
            name=t.name,
            width_in=t.width_in,
            height_in=t.height_in,
            dpi=t.dpi,
            width_px=t.width_px,
            height_px=t.height_px,
            orientation=t.orientation.value,
            photos_per_output=t.photos_per_output,
            captures_per_session=t.captures_per_session,
            outputs_per_session=t.outputs_per_session,
            links=TemplateLinks(
                spec=f"{base}{query}",
                blank_png=f"{base}/blank.png{query}",
                guide_png=f"{base}/guide.png{query}",
                sample_jpgs=[
                    f"/api/render/samples/{t.key}/{i}.jpg{query}"
                    for i in range(1, t.outputs_per_session + 1)
                ],
            ),
        )


class TemplateSpec(TemplateSummary):
    output_capture_groups: list[list[int]]
    slots: list[SlotModel]
    safe_area_inset: int
    safe_area: RectModel
    bleed: int
    branding_area: RectModel | None
    frame_rules: FrameRulesModel
    frame_requirements: list[str]

    @classmethod
    def of(cls, t: PhotoTemplate) -> TemplateSpec:
        summary = TemplateSummary.of(t)
        return cls(
            **summary.model_dump(),
            output_capture_groups=[list(group) for group in t.output_capture_groups],
            slots=[
                SlotModel(
                    index=s.index,
                    x=s.rect.x,
                    y=s.rect.y,
                    w=s.rect.w,
                    h=s.rect.h,
                    fit=s.fit,
                    anchor=s.anchor,
                    aspect=s.aspect_label,
                )
                for s in t.slots
            ],
            safe_area_inset=t.safe_area_inset,
            safe_area=RectModel.of(t.safe_area),
            bleed=t.bleed,
            branding_area=None if t.branding_area is None else RectModel.of(t.branding_area),
            frame_rules=FrameRulesModel(**t.frame_rules.__dict__),
            frame_requirements=t.frame_requirements(),
        )
