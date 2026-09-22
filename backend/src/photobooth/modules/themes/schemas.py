"""Theme API schemas."""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from photobooth.modules.themes.domain import (
    CONTRAST_RULES,
    TOKEN_KEYS,
    TOKENS,
    EventTheme,
    Preset,
    ThemeSource,
)

Color = Annotated[str, Field(pattern=r"^#[0-9A-Fa-f]{6}$", examples=["#2F6FD6"])]
TokenKey = Annotated[str, Field(pattern=r"^[a-z_]{1,40}$")]
AssetId = Annotated[
    str, Field(pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
]


class TokenInfo(BaseModel):
    key: str
    group: str
    label: str
    description: str


class ContrastRuleInfo(BaseModel):
    foreground: str
    background: str
    minimum: float
    what: str


class PresetInfo(BaseModel):
    id: str
    name: str
    description: str
    frame_family: str = Field(description="Built-in frame family that suits this preset")
    tokens: dict[str, str]


class ThemeCatalogResponse(BaseModel):
    tokens: list[TokenInfo]
    contrast_rules: list[ContrastRuleInfo]
    presets: list[PresetInfo]
    default_preset: str

    @classmethod
    def of(cls, presets: tuple[Preset, ...], default_preset: str) -> ThemeCatalogResponse:
        return cls(
            tokens=[
                TokenInfo(key=t.key, group=t.group, label=t.label, description=t.description)
                for t in TOKENS
            ],
            contrast_rules=[
                ContrastRuleInfo(
                    foreground=r.foreground, background=r.background, minimum=r.minimum, what=r.what
                )
                for r in CONTRAST_RULES
            ],
            presets=[
                PresetInfo(
                    id=p.id,
                    name=p.name,
                    description=p.description,
                    frame_family=p.frame_family,
                    tokens=dict(p.tokens),
                )
                for p in presets
            ],
            default_preset=default_preset,
        )


class ExtractBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    background_asset_id: AssetId


class ExtractedTheme(BaseModel):
    tokens: dict[str, str]
    source: ThemeSource
    preset: str | None
    palette: list[str]
    message: str = "Colors extracted from background"

    @classmethod
    def of(cls, theme: EventTheme) -> ExtractedTheme:
        return cls(
            tokens=dict(theme.tokens),
            source=theme.source,
            preset=theme.preset,
            palette=list(theme.palette),
        )


class MainColoursBody(BaseModel):
    """The current complete theme and the two colours an organizer chose."""

    model_config = ConfigDict(extra="forbid")

    tokens: dict[TokenKey, Color] = Field(min_length=len(TOKEN_KEYS), max_length=len(TOKEN_KEYS))
    button: Color = Field(description="Button colour (the main action colour)")
    text: Color = Field(description="Text colour (headings and participant text)")


class MainColoursResponse(BaseModel):
    tokens: dict[str, str] = Field(description="Every token, with the related ones regenerated")
    button: str = Field(description="The Button colour as used (adjusted only for contrast)")
    text: str = Field(description="The Text colour as used (adjusted only for contrast)")
