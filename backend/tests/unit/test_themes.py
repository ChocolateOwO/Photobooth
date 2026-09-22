"""Event themes: complete tokens, WCAG AA presets and derivation, palette extraction."""

from __future__ import annotations

import io
import random

import pytest
from PIL import Image, ImageDraw

from photobooth.modules.themes.domain import (
    CONTRAST_RULES,
    DEFAULT_PRESET,
    PRESET_LIST,
    PRESETS,
    TOKEN_KEYS,
    EventTheme,
    PaletteColor,
    ThemeSeed,
    ThemeSource,
    ThemeSourceError,
    contrast,
    contrast_problems,
    default_theme,
    derive_theme,
    is_dark,
    main_colours,
    seed_from_palette,
    theme_from_legacy,
    theme_from_palette,
    to_rgb,
    with_main_colours,
)
from photobooth.modules.themes.extractor import PillowPaletteExtractor


def _assert_accessible(tokens: dict[str, str] | EventTheme) -> None:
    values = tokens.tokens if isinstance(tokens, EventTheme) else tokens
    assert set(values) == set(TOKEN_KEYS)
    problems = contrast_problems(values)
    assert problems == [], [p.message for p in problems]


def test_the_token_set_covers_every_event_facing_element() -> None:
    required = {
        "background", "surface", "overlay", "heading", "body", "muted", "link",
        "primary_bg", "primary_text", "primary_hover", "primary_pressed",
        "primary_disabled_bg", "primary_disabled_text",
        "secondary_bg", "secondary_text", "secondary_hover", "secondary_pressed",
        "secondary_disabled_bg", "secondary_disabled_text",
        "danger_bg", "danger_text",
        "input_bg", "input_text", "input_border", "input_focus_border", "placeholder",
        "focus_ring",
        "success_bg", "success_text", "warning_bg", "warning_text",
        "error_bg", "error_text", "info_bg", "info_text",
    }  # fmt: skip
    assert set(TOKEN_KEYS) == required
    assert len(TOKEN_KEYS) == len(set(TOKEN_KEYS))
    # Every normal-text pair is held to 4.5:1, every border/focus pair to 3:1.
    minimums = {(r.foreground, r.background): r.minimum for r in CONTRAST_RULES}
    assert minimums[("primary_text", "primary_bg")] == 4.5
    assert minimums[("placeholder", "input_bg")] == 4.5
    assert minimums[("focus_ring", "background")] == 3.0


def test_at_least_six_complete_accessible_presets() -> None:
    assert len(PRESET_LIST) >= 6
    assert DEFAULT_PRESET in PRESETS
    for preset in PRESET_LIST:
        _assert_accessible(preset.tokens)
        assert preset.frame_family in {"minimal_light", "midnight", "celebration_gold"}
    # Coordinated, not all the same: the presets differ in page and button colours.
    assert len({p.tokens["background"] for p in PRESET_LIST}) == len(PRESET_LIST)
    assert len({p.tokens["primary_bg"] for p in PRESET_LIST}) == len(PRESET_LIST)
    default = default_theme()
    assert default.source is ThemeSource.PRESET and default.preset == DEFAULT_PRESET


def test_derived_themes_are_always_accessible() -> None:
    rng = random.Random(491)

    def colour() -> tuple[int, int, int]:
        return (rng.randrange(256), rng.randrange(256), rng.randrange(256))

    for index in range(600):
        seed = ThemeSeed(colour(), colour(), colour() if index % 2 else None)
        _assert_accessible(derive_theme(seed))
    # The hard cases: mid grey everywhere, and accents equal to the page colour.
    for grey in ((119, 119, 119), (128, 128, 128), (0, 0, 0), (255, 255, 255)):
        _assert_accessible(derive_theme(ThemeSeed(grey, grey, grey)))


def test_text_is_light_or_dark_by_measured_contrast() -> None:
    dark = derive_theme(ThemeSeed((12, 12, 30), (200, 60, 60)))
    light = derive_theme(ThemeSeed((250, 245, 235), (200, 60, 60)))
    assert contrast(to_rgb(dark["heading"]), (255, 255, 255)) < 1.1  # light text on dark
    assert contrast(to_rgb(light["heading"]), (0, 0, 0)) < 1.6  # dark text on light
    assert is_dark(dark) and not is_dark(light)
    # Hover and pressed states differ from the resting button and keep the label readable.
    assert len({dark["primary_bg"], dark["primary_hover"], dark["primary_pressed"]}) == 3


def test_theme_validation_reports_missing_unknown_and_malformed_colours() -> None:
    tokens = dict(PRESETS[DEFAULT_PRESET].tokens)
    assert EventTheme(tokens).problems() == []
    missing = {k: v for k, v in tokens.items() if k != "heading"}
    assert "missing colours: heading" in EventTheme(missing).problems()[0]
    assert "unknown colours: sparkle" in EventTheme({**tokens, "sparkle": "#FFFFFF"}).problems()[0]
    assert "#RRGGBB" in EventTheme({**tokens, "heading": "white"}).problems()[0]
    assert "unknown theme preset" in EventTheme(tokens, preset="nope").problems()[0]
    lower = EventTheme({**tokens, "heading": "#abcdef"}, palette=("#0a0b0c",)).normalized()
    assert lower.tokens["heading"] == "#ABCDEF" and lower.palette == ("#0A0B0C",)


def test_manual_choices_are_reported_not_silently_accepted() -> None:
    tokens = {**PRESETS["minimal_light"].tokens, "heading": "#F8FAFC", "primary_text": "#2563EB"}
    problems = {p.what for p in contrast_problems(tokens)}
    assert {"Headings", "Main button text"} <= problems


def test_legacy_profile_colours_become_a_complete_accessible_theme() -> None:
    # The Phase 3 defaults, and a deliberately poor old combination (grey on grey).
    for legacy in (
        ("#101418", "#2F6FD6", "#FFB020", "#2F6FD6"),
        ("#777777", "#787878", "#767676", "#777777"),
        ("#FFFFFF", "#FFFF00", "#FFFFFF", "#FFFFEE"),
    ):
        theme = theme_from_legacy(*legacy)
        assert theme.source is ThemeSource.CUSTOM
        _assert_accessible(theme)


# ---- palette extraction ------------------------------------------------------------------------


def _image(draw: object, size: tuple[int, int] = (400, 300), fmt: str = "JPEG") -> bytes:
    image = Image.new("RGB", size, (0, 0, 0))
    assert callable(draw)
    draw(image, ImageDraw.Draw(image))
    buffer = io.BytesIO()
    image.save(buffer, fmt)
    return buffer.getvalue()


def _light(image: Image.Image, d: ImageDraw.ImageDraw) -> None:
    d.rectangle((0, 0, 400, 300), fill=(246, 240, 228))
    d.ellipse((140, 80, 260, 200), fill=(214, 64, 96))


def _dark(image: Image.Image, d: ImageDraw.ImageDraw) -> None:
    d.rectangle((0, 0, 400, 300), fill=(14, 20, 48))
    d.rectangle((0, 220, 400, 300), fill=(40, 170, 160))


def _mono(image: Image.Image, d: ImageDraw.ImageDraw) -> None:
    for x in range(400):
        d.line((x, 0, x, 300), fill=(x * 255 // 400,) * 3)


def _low_contrast(image: Image.Image, d: ImageDraw.ImageDraw) -> None:
    d.rectangle((0, 0, 400, 300), fill=(128, 126, 124))
    d.rectangle((100, 100, 300, 200), fill=(134, 130, 128))


@pytest.mark.parametrize(
    ("painter", "dark_page"),
    [(_light, False), (_dark, True), (_mono, None), (_low_contrast, None)],
)
def test_backgrounds_give_accessible_themes(painter: object, dark_page: bool | None) -> None:
    data = _image(painter)
    palette = PillowPaletteExtractor().extract(data)
    assert 1 <= len(palette) <= 10
    assert 0.9 <= sum(c.share for c in palette) <= 1.0001  # tiny specks may be dropped
    theme = theme_from_palette(palette)
    assert theme.source is ThemeSource.EXTRACTED
    assert 1 <= len(theme.palette) <= 8
    _assert_accessible(theme)
    if dark_page is not None:
        assert is_dark(theme.tokens) is dark_page


def test_the_accent_comes_from_the_image_and_grey_images_get_a_calm_default() -> None:
    light = seed_from_palette(PillowPaletteExtractor().extract(_image(_light)))
    r, g, b = light.accent
    assert r > g and r > b  # the rose circle, not the cream page
    mono = seed_from_palette(PillowPaletteExtractor().extract(_image(_mono)))
    assert mono.accent == (47, 111, 214)


def test_extraction_reads_png_with_transparency_and_never_changes_the_bytes() -> None:
    image = Image.new("RGBA", (200, 200), (0, 0, 0, 0))
    ImageDraw.Draw(image).rectangle((50, 50, 150, 150), fill=(20, 120, 60, 255))
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    data = buffer.getvalue()
    before = bytes(data)
    palette = PillowPaletteExtractor().extract(data)
    assert data == before
    assert palette[0].rgb[1] > palette[0].rgb[0]  # the green square; transparent pixels ignored


def test_unreadable_images_give_a_plain_error() -> None:
    with pytest.raises(ThemeSourceError, match="could not be read"):
        PillowPaletteExtractor().extract(b"not an image")
    blank = Image.new("RGBA", (20, 20), (0, 0, 0, 0))
    buffer = io.BytesIO()
    blank.save(buffer, "PNG")
    with pytest.raises(ThemeSourceError, match="no visible pixels"):
        PillowPaletteExtractor().extract(buffer.getvalue())


def test_empty_palette_falls_back_safely() -> None:
    _assert_accessible(theme_from_palette([]))
    _assert_accessible(theme_from_palette([PaletteColor((128, 128, 128), 1.0)]))


@pytest.mark.parametrize("preset", PRESET_LIST, ids=lambda p: p.id)
def test_main_colours_always_give_an_accessible_related_theme(preset: object) -> None:
    base = PRESETS[preset.id].tokens  # type: ignore[attr-defined]
    rng = random.Random(preset.id)  # type: ignore[attr-defined]
    for _ in range(150):
        button = f"#{rng.randrange(1 << 24):06X}"
        text = f"#{rng.randrange(1 << 24):06X}"
        tokens = with_main_colours(base, button, text)
        assert set(tokens) == set(TOKEN_KEYS)
        # Only the page and status colours stay as they were; everything meets the rules.
        for key in ("background", "surface", "overlay", "input_bg"):
            assert tokens[key] == base[key]
        assert contrast_problems(tokens) == []
        # The chosen hue survives (only its lightness/saturation move, for contrast).
        assert (
            tokens["primary_bg"] == button
            or contrast(to_rgb(tokens["primary_bg"]), to_rgb(tokens["primary_text"])) >= 4.5
        )


def test_main_colours_are_read_from_and_round_trip_through_the_tokens() -> None:
    for preset in PRESET_LIST:
        button, text = main_colours(preset.tokens)
        assert (button, text) == (preset.tokens["primary_bg"], preset.tokens["heading"])
        again = with_main_colours(preset.tokens, button, text)
        assert main_colours(again) == (button, text)
        assert contrast_problems(again) == []


def test_main_colours_repair_a_custom_theme_whose_page_colours_clash() -> None:
    # A black page with grey cards and inputs: no one text colour reads on all three.
    base = dict(PRESETS[DEFAULT_PRESET].tokens)
    base.update(background="#000000", surface="#808080", input_bg="#808080")
    tokens = with_main_colours(base, base["primary_bg"], "#FFFFFF")
    assert contrast_problems(tokens) == []
    assert tokens["background"] == "#000000"
    assert tokens["heading"] == "#FFFFFF"
    assert tokens["surface"] != "#808080"  # darkened just enough to carry the white text


def test_main_colours_always_give_an_accessible_theme_from_any_custom_theme() -> None:
    # Any complete theme the old 35-colour editor could have saved, with any two main colours.
    rng = random.Random("custom")

    def colour() -> str:
        return f"#{rng.randrange(1 << 24):06X}"

    for _ in range(400):
        base = {key: colour() for key in TOKEN_KEYS}
        tokens = with_main_colours(base, colour(), colour())
        assert set(tokens) == set(TOKEN_KEYS)
        assert contrast_problems(tokens) == [], contrast_problems(tokens)[0].message
        assert tokens["background"] == base["background"]
