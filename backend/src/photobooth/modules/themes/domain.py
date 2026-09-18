"""Event theme domain: semantic tokens, WCAG contrast, accessible derivation and presets.

A theme is a complete set of semantic colour tokens for every event-facing element (kiosk
screens and their preview). The admin shell never follows it. Presets and every generated theme
(from a background image or from pre-theme profile colours) are derived by `derive_theme`, which
only returns colour pairs meeting WCAG AA; hand-edited tokens are allowed but reported by
`contrast_problems` so the admin sees every unreadable pair.
"""

from __future__ import annotations

import colorsys
import math
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum

HEX = re.compile(r"^#[0-9A-F]{6}$")
RGB = tuple[int, int, int]

TEXT_AA = 4.5  # WCAG AA, normal text and button labels
NON_TEXT_AA = 3.0  # WCAG AA, borders, focus indicators; also the floor for disabled labels
HEADING_TARGET = 7.0  # headings get more headroom than the AA minimum

WHITE: RGB = (255, 255, 255)
LIGHT_TEXT: RGB = (248, 250, 252)
DARK_TEXT: RGB = (15, 23, 42)
DEFAULT_ACCENT: RGB = (47, 111, 214)
PALETTE_MAX = 8


class ThemeSourceError(Exception):
    """The background image can not be used for colour extraction (plain message)."""


class ThemeSource(StrEnum):
    PRESET = "preset"  # one of the presets, unchanged
    EXTRACTED = "extracted"  # generated from the profile background image
    CUSTOM = "custom"  # edited by hand, or converted from pre-theme profile colours


@dataclass(frozen=True)
class TokenSpec:
    key: str
    group: str
    label: str
    description: str


TOKENS: tuple[TokenSpec, ...] = (
    TokenSpec(
        "background",
        "Page",
        "Page background",
        "Behind everything, and around the background image.",
    ),
    TokenSpec("surface", "Page", "Cards and dialogs", "Panels, cards and pop-up dialogs."),
    TokenSpec(
        "overlay", "Page", "Backdrop", "Dims the screen behind a dialog (shown see-through)."
    ),
    TokenSpec("heading", "Text", "Headings", "Titles such as the welcome heading."),
    TokenSpec("body", "Text", "Body text", "Normal sentences and instructions."),
    TokenSpec("muted", "Text", "Helper text", "Less important hints and captions."),
    TokenSpec("link", "Text", "Links", "Text links guests can tap."),
    TokenSpec("primary_bg", "Main button", "Main button", "The main action, e.g. Start."),
    TokenSpec("primary_text", "Main button", "Main button text", "Label on the main button."),
    TokenSpec("primary_hover", "Main button", "Main button (hover)", "When a pointer is over it."),
    TokenSpec(
        "primary_pressed", "Main button", "Main button (pressed)", "While it is being pressed."
    ),
    TokenSpec(
        "primary_disabled_bg",
        "Main button",
        "Main button (disabled)",
        "When it can not be used yet.",
    ),
    TokenSpec(
        "primary_disabled_text", "Main button", "Disabled main button text", "Label while disabled."
    ),
    TokenSpec(
        "secondary_bg", "Other buttons", "Other buttons", "Less important actions, e.g. Back."
    ),
    TokenSpec("secondary_text", "Other buttons", "Other button text", "Label on other buttons."),
    TokenSpec(
        "secondary_hover", "Other buttons", "Other buttons (hover)", "When a pointer is over it."
    ),
    TokenSpec(
        "secondary_pressed",
        "Other buttons",
        "Other buttons (pressed)",
        "While it is being pressed.",
    ),
    TokenSpec(
        "secondary_disabled_bg",
        "Other buttons",
        "Other buttons (disabled)",
        "When it can not be used yet.",
    ),
    TokenSpec(
        "secondary_disabled_text",
        "Other buttons",
        "Disabled other button text",
        "Label while disabled.",
    ),
    TokenSpec(
        "danger_bg", "Other buttons", "Delete / cancel button", "Actions that remove something."
    ),
    TokenSpec(
        "danger_text", "Other buttons", "Delete / cancel button text", "Label on that button."
    ),
    TokenSpec("input_bg", "Inputs", "Input background", "Inside text boxes, e.g. an email field."),
    TokenSpec("input_text", "Inputs", "Input text", "What a guest types."),
    TokenSpec("input_border", "Inputs", "Input border", "The outline of a text box."),
    TokenSpec(
        "input_focus_border",
        "Inputs",
        "Input border (active)",
        "Outline of the box being typed in.",
    ),
    TokenSpec(
        "placeholder", "Inputs", "Example text in inputs", "Grey example shown in an empty box."
    ),
    TokenSpec(
        "focus_ring", "Inputs", "Focus indicator", "Ring around the control chosen by keyboard."
    ),
    TokenSpec("success_bg", "Messages", "Success message", "Background of a 'done' message."),
    TokenSpec("success_text", "Messages", "Success message text", "Text of a 'done' message."),
    TokenSpec("warning_bg", "Messages", "Warning message", "Background of a warning."),
    TokenSpec("warning_text", "Messages", "Warning message text", "Text of a warning."),
    TokenSpec("error_bg", "Messages", "Error message", "Background of an error."),
    TokenSpec("error_text", "Messages", "Error message text", "Text of an error."),
    TokenSpec("info_bg", "Messages", "Information message", "Background of a hint or notice."),
    TokenSpec("info_text", "Messages", "Information message text", "Text of a hint or notice."),
)
TOKEN_KEYS: tuple[str, ...] = tuple(spec.key for spec in TOKENS)


@dataclass(frozen=True)
class ContrastRule:
    foreground: str
    background: str
    minimum: float
    what: str


def _text(fg: str, bgs: Iterable[str], what: str) -> list[ContrastRule]:
    return [ContrastRule(fg, bg, TEXT_AA, what) for bg in bgs]


CONTRAST_RULES: tuple[ContrastRule, ...] = (
    *_text("heading", ("background", "surface"), "Headings"),
    *_text("body", ("background", "surface"), "Body text"),
    *_text("muted", ("background", "surface"), "Helper text"),
    *_text("link", ("background", "surface"), "Links"),
    *_text("primary_text", ("primary_bg", "primary_hover", "primary_pressed"), "Main button text"),
    *_text(
        "secondary_text",
        ("secondary_bg", "secondary_hover", "secondary_pressed"),
        "Other button text",
    ),
    *_text("danger_text", ("danger_bg",), "Delete button text"),
    *_text("input_text", ("input_bg",), "Input text"),
    *_text("placeholder", ("input_bg",), "Example text in inputs"),
    *_text("success_text", ("success_bg",), "Success message"),
    *_text("warning_text", ("warning_bg",), "Warning message"),
    *_text("error_text", ("error_bg",), "Error message"),
    *_text("info_text", ("info_bg",), "Information message"),
    ContrastRule(
        "primary_disabled_text", "primary_disabled_bg", NON_TEXT_AA, "Disabled main button"
    ),
    ContrastRule(
        "secondary_disabled_text", "secondary_disabled_bg", NON_TEXT_AA, "Disabled other button"
    ),
    ContrastRule("input_border", "input_bg", NON_TEXT_AA, "Input border"),
    ContrastRule("input_focus_border", "input_bg", NON_TEXT_AA, "Active input border"),
    ContrastRule("focus_ring", "background", NON_TEXT_AA, "Focus indicator"),
    ContrastRule("focus_ring", "surface", NON_TEXT_AA, "Focus indicator on cards"),
)


# ---- colour math --------------------------------------------------------------------------------


def to_rgb(value: str) -> RGB:
    return (int(value[1:3], 16), int(value[3:5], 16), int(value[5:7], 16))


def to_hex(rgb: Sequence[float]) -> str:
    r, g, b = (max(0, min(255, round(c))) for c in rgb)
    return f"#{r:02X}{g:02X}{b:02X}"


def _linear(channel: int) -> float:
    c = channel / 255
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def luminance(rgb: RGB) -> float:
    r, g, b = rgb
    return 0.2126 * _linear(r) + 0.7152 * _linear(g) + 0.0722 * _linear(b)


def contrast(a: RGB, b: RGB) -> float:
    la, lb = luminance(a), luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def mix(a: RGB, b: RGB, amount: float) -> RGB:
    """`amount` of b mixed into a."""
    return (
        round(a[0] + (b[0] - a[0]) * amount),
        round(a[1] + (b[1] - a[1]) * amount),
        round(a[2] + (b[2] - a[2]) * amount),
    )


def hls(rgb: RGB) -> tuple[float, float, float]:
    return colorsys.rgb_to_hls(rgb[0] / 255, rgb[1] / 255, rgb[2] / 255)


def from_hls(h: float, lightness: float, s: float) -> RGB:
    r, g, b = colorsys.hls_to_rgb(h, lightness, s)
    return (round(r * 255), round(g * 255), round(b * 255))


def saturation(rgb: RGB) -> float:
    """Chroma-like saturation in 0..1 (low for greys, including near-black and near-white)."""
    return (max(rgb) - min(rgb)) / 255


Constraint = tuple[RGB, float]


def _meets(rgb: RGB, constraints: Iterable[Constraint]) -> bool:
    return all(contrast(rgb, other) >= minimum for other, minimum in constraints)


def fit(rgb: RGB, required: Sequence[Constraint], preferred: Sequence[Constraint] = ()) -> RGB:
    """Keep the hue, change lightness (then saturation) as little as possible to meet `required`
    (and, when possible, `preferred`) contrast minimums. Always returns a colour meeting
    `required`: pure black or white is the last resort and always reaches 4.5:1 against one side.
    """
    if _meets(rgb, [*required, *preferred]):
        return rgb
    h, l0, s0 = hls(rgb)
    steps = sorted((i / 100 for i in range(101)), key=lambda value: abs(value - l0))
    for wanted in ([*required, *preferred], list(required)):
        for s in (s0, s0 * 0.6, 0.0):
            for lightness in steps:
                candidate = from_hls(h, lightness, s)
                if _meets(candidate, wanted):
                    return candidate
    black, white = (0, 0, 0), WHITE
    return max((black, white), key=lambda c: min((contrast(c, o) for o, _m in required), default=0))


def best_text(bg: RGB) -> RGB:
    return LIGHT_TEXT if contrast(LIGHT_TEXT, bg) >= contrast(DARK_TEXT, bg) else DARK_TEXT


# ---- derivation -------------------------------------------------------------------------------


@dataclass(frozen=True)
class ThemeSeed:
    background: RGB
    accent: RGB
    accent2: RGB | None = None


@dataclass(frozen=True)
class _Button:
    bg: RGB
    text: RGB
    hover: RGB
    pressed: RGB
    disabled_bg: RGB
    disabled_text: RGB


def _button(color: RGB, page: RGB) -> _Button:
    """An accessible filled button of this hue, visible against the page (3:1 when possible)."""

    def cost(text: RGB) -> tuple[float, RGB]:
        candidate = fit(color, [(text, TEXT_AA)], [(page, NON_TEXT_AA)])
        moved = abs(hls(candidate)[1] - hls(color)[1])
        hidden = 0.0 if contrast(candidate, page) >= NON_TEXT_AA else 1.0
        # White labels read best on coloured buttons: accept a slightly larger lightness change.
        bias = -0.08 if text == LIGHT_TEXT and saturation(color) >= 0.2 else 0.0
        return moved + hidden + bias, candidate

    scored = [(cost(text), text) for text in (LIGHT_TEXT, DARK_TEXT)]
    (_score, bg), text = min(scored, key=lambda item: item[0][0])
    bg = fit(bg, [(text, TEXT_AA)])
    # Hover and pressed move away from the label colour, so their contrast only grows.
    direction = -1 if text == LIGHT_TEXT else 1
    h, lightness, s = hls(bg)
    hover = fit(from_hls(h, min(1, max(0, lightness + direction * 0.06)), s), [(text, TEXT_AA)])
    pressed = fit(from_hls(h, min(1, max(0, lightness + direction * 0.12)), s), [(text, TEXT_AA)])
    disabled_bg = mix(bg, page, 0.55)
    disabled_text = fit(mix(text, disabled_bg, 0.35), [(disabled_bg, NON_TEXT_AA)])
    return _Button(bg, text, hover, pressed, disabled_bg, disabled_text)


def _status(base: RGB, surface: RGB) -> tuple[RGB, RGB]:
    bg = mix(base, surface, 0.84)
    return bg, fit(base, [(bg, TEXT_AA)])


def derive_theme(seed: ThemeSeed) -> dict[str, str]:
    """A complete accessible token set from a background colour and one or two accents."""
    heading = best_text(seed.background)
    dark = heading == LIGHT_TEXT
    background = fit(seed.background, [(heading, HEADING_TARGET)])
    surface = fit(mix(background, WHITE, 0.08 if dark else 0.75), [(heading, HEADING_TARGET)])
    input_bg = surface if dark else WHITE
    body = fit(mix(heading, background, 0.1), [(background, TEXT_AA), (surface, TEXT_AA)])
    muted = fit(
        mix(heading, background, 0.36),
        [(background, TEXT_AA), (surface, TEXT_AA), (input_bg, TEXT_AA)],
    )
    link = fit(seed.accent, [(background, TEXT_AA), (surface, TEXT_AA)])
    primary = _button(seed.accent, background)
    if seed.accent2 is not None:
        secondary = _button(seed.accent2, background)
    else:
        secondary = _button(mix(background, heading, 0.16), background)
    danger = _button((220, 38, 38), background)
    input_border = fit(mix(heading, input_bg, 0.5), [(input_bg, NON_TEXT_AA)])
    focus_border = fit(primary.bg, [(input_bg, NON_TEXT_AA)])
    focus_ring = fit(link, [(background, NON_TEXT_AA), (surface, NON_TEXT_AA)])
    success = _status((22, 163, 74), surface)
    warning = _status((217, 119, 6), surface)
    error = _status((220, 38, 38), surface)
    info = _status((37, 99, 235), surface)
    tokens: dict[str, RGB] = {
        "background": background,
        "surface": surface,
        "overlay": (0, 0, 0) if dark else DARK_TEXT,
        "heading": heading,
        "body": body,
        "muted": muted,
        "link": link,
        "primary_bg": primary.bg,
        "primary_text": primary.text,
        "primary_hover": primary.hover,
        "primary_pressed": primary.pressed,
        "primary_disabled_bg": primary.disabled_bg,
        "primary_disabled_text": primary.disabled_text,
        "secondary_bg": secondary.bg,
        "secondary_text": secondary.text,
        "secondary_hover": secondary.hover,
        "secondary_pressed": secondary.pressed,
        "secondary_disabled_bg": secondary.disabled_bg,
        "secondary_disabled_text": secondary.disabled_text,
        "danger_bg": danger.bg,
        "danger_text": danger.text,
        "input_bg": input_bg,
        "input_text": heading,
        "input_border": input_border,
        "input_focus_border": focus_border,
        "placeholder": muted,
        "focus_ring": focus_ring,
        "success_bg": success[0],
        "success_text": success[1],
        "warning_bg": warning[0],
        "warning_text": warning[1],
        "error_bg": error[0],
        "error_text": error[1],
        "info_bg": info[0],
        "info_text": info[1],
    }
    return {key: to_hex(tokens[key]) for key in TOKEN_KEYS}


@dataclass(frozen=True)
class ContrastProblem:
    what: str
    foreground: str
    background: str
    ratio: float
    minimum: float

    @property
    def message(self) -> str:
        return (
            f"{self.what}: contrast {self.ratio:.1f}:1 is below {self.minimum:g}:1 "
            f"({self.foreground} on {self.background})."
        )


def contrast_problems(tokens: Mapping[str, str]) -> list[ContrastProblem]:
    found = []
    for rule in CONTRAST_RULES:
        ratio = contrast(to_rgb(tokens[rule.foreground]), to_rgb(tokens[rule.background]))
        if ratio + 1e-9 < rule.minimum:
            found.append(
                ContrastProblem(rule.what, rule.foreground, rule.background, ratio, rule.minimum)
            )
    return found


# ---- themes and presets -----------------------------------------------------------------------


@dataclass(frozen=True)
class EventTheme:
    tokens: Mapping[str, str]
    source: ThemeSource = ThemeSource.CUSTOM
    preset: str | None = None
    # Swatches taken from the background image when source is EXTRACTED (shown to the admin).
    palette: tuple[str, ...] = field(default=())

    def problems(self) -> list[str]:
        found: list[str] = []
        keys = set(self.tokens)
        missing = [key for key in TOKEN_KEYS if key not in keys]
        unknown = sorted(keys - set(TOKEN_KEYS))
        if missing:
            found.append(f"theme is missing colours: {', '.join(missing)}")
        if unknown:
            found.append(f"theme has unknown colours: {', '.join(unknown)}")
        bad = [key for key, value in self.tokens.items() if not HEX.fullmatch(value)]
        if bad:
            found.append(f"theme colours must be #RRGGBB: {', '.join(sorted(bad))}")
        if self.preset is not None and self.preset not in PRESETS:
            found.append(f"unknown theme preset: {self.preset}")
        if len(self.palette) > PALETTE_MAX or not all(HEX.fullmatch(c) for c in self.palette):
            found.append(f"theme palette must be at most {PALETTE_MAX} #RRGGBB colours")
        return found

    def normalized(self) -> EventTheme:
        return EventTheme(
            tokens={key: value.upper() for key, value in self.tokens.items()},
            source=self.source,
            preset=self.preset,
            palette=tuple(c.upper() for c in self.palette),
        )


@dataclass(frozen=True)
class Preset:
    id: str
    name: str
    description: str
    seed: ThemeSeed
    frame_family: str  # the built-in frame family that suits it

    @property
    def tokens(self) -> dict[str, str]:
        return _PRESET_TOKENS[self.id]


def _preset(
    id: str, name: str, description: str, bg: str, accent: str, accent2: str, frames: str
) -> Preset:
    return Preset(
        id, name, description, ThemeSeed(to_rgb(bg), to_rgb(accent), to_rgb(accent2)), frames
    )


PRESET_LIST: tuple[Preset, ...] = (
    _preset(
        "midnight_blue",
        "Midnight Blue",
        "Deep navy with a bright blue button and warm amber.",
        "#0F172A",
        "#3B82F6",
        "#F59E0B",
        "midnight",
    ),
    _preset(
        "minimal_light",
        "Minimal Light",
        "Clean white with a crisp blue accent.",
        "#F8FAFC",
        "#2563EB",
        "#0F172A",
        "minimal_light",
    ),
    _preset(
        "celebration_gold",
        "Celebration Gold",
        "Warm espresso with festive gold.",
        "#1C1917",
        "#D4A017",
        "#F5E6C8",
        "celebration_gold",
    ),
    _preset(
        "blush_wedding",
        "Blush Wedding",
        "Soft blush pink with deep rose.",
        "#FFF1F2",
        "#BE185D",
        "#9F1239",
        "minimal_light",
    ),
    _preset(
        "forest_fresh",
        "Forest Fresh",
        "Light mint with forest green.",
        "#F0FDF4",
        "#15803D",
        "#065F46",
        "minimal_light",
    ),
    _preset(
        "neon_party",
        "Neon Party",
        "Dark violet with neon magenta and cyan.",
        "#140B2E",
        "#D946EF",
        "#22D3EE",
        "midnight",
    ),
    _preset(
        "sunset_coral",
        "Sunset Coral",
        "Warm cream with coral orange.",
        "#FFF7ED",
        "#EA580C",
        "#7C2D12",
        "celebration_gold",
    ),
)
PRESETS: dict[str, Preset] = {preset.id: preset for preset in PRESET_LIST}
_PRESET_TOKENS: dict[str, dict[str, str]] = {p.id: derive_theme(p.seed) for p in PRESET_LIST}
DEFAULT_PRESET = "midnight_blue"


def preset_theme(preset_id: str) -> EventTheme:
    return EventTheme(
        tokens=dict(PRESETS[preset_id].tokens), source=ThemeSource.PRESET, preset=preset_id
    )


def default_theme() -> EventTheme:
    return preset_theme(DEFAULT_PRESET)


def theme_from_legacy(background: str, primary: str, secondary: str, button: str) -> EventTheme:
    """A complete accessible theme from the pre-theme profile colours (migration 0004)."""
    accent = (
        to_rgb(button)
        if saturation(to_rgb(button)) >= saturation(to_rgb(primary))
        else to_rgb(primary)
    )
    seed = ThemeSeed(to_rgb(background), accent, to_rgb(secondary))
    return EventTheme(tokens=derive_theme(seed), source=ThemeSource.CUSTOM)


def is_dark(tokens: Mapping[str, str]) -> bool:
    return luminance(to_rgb(tokens["background"])) < 0.18


# ---- palette -> theme -------------------------------------------------------------------------


@dataclass(frozen=True)
class PaletteColor:
    rgb: RGB
    share: float  # fraction of the image's pixels


def _hue_distance(a: RGB, b: RGB) -> float:
    d = abs(hls(a)[0] - hls(b)[0])
    return min(d, 1 - d)


def seed_from_palette(palette: Sequence[PaletteColor]) -> ThemeSeed:
    """Dominant colour -> page background; most vivid prominent colour -> accent; a second hue
    (when the image has one) -> accent2. Grey images fall back to a calm default accent."""
    if not palette:
        return ThemeSeed((16, 20, 24), DEFAULT_ACCENT)
    ordered = sorted(palette, key=lambda c: -c.share)
    background = ordered[0].rgb

    def vividness(c: PaletteColor) -> float:
        return float(saturation(c.rgb) * math.sqrt(0.35 + c.share))

    vivid = sorted((c for c in ordered if saturation(c.rgb) >= 0.18), key=lambda c: -vividness(c))
    if not vivid:
        return ThemeSeed(background, DEFAULT_ACCENT)
    accent = vivid[0].rgb
    second = next((c.rgb for c in vivid[1:] if _hue_distance(c.rgb, accent) >= 0.08), None)
    return ThemeSeed(background, accent, second)


def theme_from_palette(palette: Sequence[PaletteColor]) -> EventTheme:
    ordered = sorted(palette, key=lambda c: -c.share)[:PALETTE_MAX]
    return EventTheme(
        tokens=derive_theme(seed_from_palette(palette)),
        source=ThemeSource.EXTRACTED,
        palette=tuple(to_hex(c.rgb) for c in ordered),
    )
