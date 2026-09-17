"""Frame validation against the approved 2x6, 3x4 and 4x6 templates (plain-language errors)."""

from __future__ import annotations

import io

import pytest
from PIL import Image, ImageCms

from photobooth.modules.frames.domain import FrameValidationError
from photobooth.modules.frames.validator import PillowFrameValidator
from photobooth.modules.templates.domain import PhotoTemplate
from photobooth.modules.templates.repository import JsonTemplateRepository

TEMPLATES = {t.key: t for t in JsonTemplateRepository().latest()}
KEYS = ("strip_2x6", "print_3x4", "print_4x6")


def frame_png(
    template: PhotoTemplate,
    *,
    mode: str = "RGBA",
    size: tuple[int, int] | None = None,
    clear_slots: bool = True,
    icc: bytes | None = None,
    animated: bool = False,
    fill: tuple[int, int, int, int] = (20, 40, 90, 255),
) -> bytes:
    width, height = size or (template.width_px, template.height_px)
    image = Image.new(mode, (width, height), fill if mode == "RGBA" else 200)
    if clear_slots and mode == "RGBA":
        for slot in template.slots:
            rect = slot.rect
            image.paste((0, 0, 0, 0), (rect.x, rect.y, rect.x + rect.w, rect.y + rect.h))
    buffer = io.BytesIO()
    extra: dict[str, object] = {}
    if icc is not None:
        extra["icc_profile"] = icc
    if animated:
        second = image.copy()
        image.save(buffer, "PNG", save_all=True, append_images=[second], **extra)
    else:
        image.save(buffer, "PNG", **extra)
    return buffer.getvalue()


@pytest.mark.parametrize("key", KEYS)
def test_accepts_a_correct_frame_for_every_approved_template(key: str) -> None:
    template = TEMPLATES[key]
    report = PillowFrameValidator().validate(frame_png(template), template)
    assert (report.width, report.height) == (template.width_px, template.height_px)
    assert report.warnings == ()
    assert len(report.slot_transparency) == len(template.slots)
    assert all(ratio == 1.0 for ratio in report.slot_transparency)


@pytest.mark.parametrize("key", KEYS)
def test_rejects_the_wrong_canvas_size_naming_both_sizes(key: str) -> None:
    template = TEMPLATES[key]
    wrong = frame_png(template, size=(template.width_px - 10, template.height_px))
    with pytest.raises(FrameValidationError) as info:
        PillowFrameValidator().validate(wrong, template)
    message = info.value.problems[0]
    assert f"exactly {template.width_px} x {template.height_px} px" in message
    assert f"{template.width_px - 10} x {template.height_px} px" in message


def test_rejects_an_opaque_photo_area_and_names_the_slot() -> None:
    template = TEMPLATES["strip_2x6"]
    with pytest.raises(FrameValidationError) as info:
        PillowFrameValidator().validate(frame_png(template, clear_slots=False), template)
    problems = info.value.problems
    assert len(problems) == len(template.slots)
    assert problems[0].startswith("Photo 1 area must be at least 95% transparent; it is 0%")
    assert "x=30, y=45, w=540, h=405" in problems[0]
    assert "Photo 3" in problems[-1]


def test_rejects_a_partly_opaque_photo_area() -> None:
    template = TEMPLATES["print_3x4"]
    image = Image.new("RGBA", (template.width_px, template.height_px), (10, 10, 10, 255))
    for slot in template.slots:
        rect = slot.rect
        image.paste((0, 0, 0, 0), (rect.x, rect.y, rect.x + rect.w, rect.y + rect.h))
    first = template.slots[0].rect  # leave 10% of photo 1 painted over
    image.paste((255, 0, 0, 255), (first.x, first.y, first.x + first.w, first.y + first.h // 10))
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    with pytest.raises(FrameValidationError, match="Photo 1 area must be at least 95%"):
        PillowFrameValidator().validate(buffer.getvalue(), template)


@pytest.mark.parametrize(
    ("data", "match"),
    [
        (b"", "empty"),
        (b"not a png", "valid PNG"),
        (b"\x89PNG\r\n\x1a\n" + b"\x00" * 200, "valid PNG"),
    ],
)
def test_rejects_files_that_are_not_usable_pngs(data: bytes, match: str) -> None:
    with pytest.raises(FrameValidationError, match=match):
        PillowFrameValidator().validate(data, TEMPLATES["strip_2x6"])


def test_rejects_a_jpeg_even_with_the_right_size() -> None:
    template = TEMPLATES["strip_2x6"]
    buffer = io.BytesIO()
    Image.new("RGB", (template.width_px, template.height_px), (1, 2, 3)).save(buffer, "JPEG")
    with pytest.raises(FrameValidationError, match="valid PNG"):
        PillowFrameValidator().validate(buffer.getvalue(), template)


def test_rejects_opaque_grayscale_and_animated_frames() -> None:
    template = TEMPLATES["strip_2x6"]
    validator = PillowFrameValidator()
    with pytest.raises(FrameValidationError, match="transparent background"):
        validator.validate(frame_png(template, mode="RGB"), template)
    with pytest.raises(FrameValidationError, match="Grayscale"):
        validator.validate(frame_png(template, mode="L"), template)
    with pytest.raises(FrameValidationError, match="must not be animated"):
        validator.validate(frame_png(template, animated=True), template)


def test_rejects_a_frame_larger_than_the_rule() -> None:
    template = TEMPLATES["strip_2x6"]
    oversized = b"\x89PNG\r\n\x1a\n" + b"\x00" * (template.frame_rules.max_bytes + 1)
    with pytest.raises(FrameValidationError, match="at most 10 MB"):
        PillowFrameValidator().validate(oversized, template)


def test_warns_about_a_non_srgb_colour_profile_without_changing_the_file() -> None:
    template = TEMPLATES["print_4x6"]
    profile = ImageCms.createProfile("LAB")
    icc = ImageCms.ImageCmsProfile(profile).tobytes()
    data = frame_png(template, icc=icc)
    report = PillowFrameValidator().validate(data, template)
    assert len(report.warnings) == 1
    assert "converted to sRGB" in report.warnings[0]
    # sRGB (and untagged) frames stay silent.
    srgb = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
    assert PillowFrameValidator().validate(frame_png(template, icc=srgb), template).warnings == ()
