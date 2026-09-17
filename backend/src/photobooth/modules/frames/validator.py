"""Pillow frame validator: checks a ready-made PNG against a template (never modifies the file)."""

from __future__ import annotations

import io
import warnings

from PIL import Image, ImageCms

from photobooth.modules.frames.domain import FrameValidationError, FrameValidationReport
from photobooth.modules.templates.domain import PhotoTemplate, SlotDefinition

# A pixel counts as transparent below this alpha value (out of 255).
TRANSPARENT_ALPHA = 8
SRGB_HINTS = ("srgb", "sgrey", "iec61966")


def _percent(value: float) -> str:
    return f"{round(value * 100)}%"


class PillowFrameValidator:
    def validate(self, data: bytes, template: PhotoTemplate) -> FrameValidationReport:
        rules = template.frame_rules
        problems: list[str] = []
        if not data:
            raise FrameValidationError(["The file is empty."])
        if len(data) > rules.max_bytes:
            raise FrameValidationError(
                [
                    f"The frame must be at most {rules.max_bytes // (1024 * 1024)} MB; "
                    f"this file is {len(data) / (1024 * 1024):.1f} MB."
                ]
            )
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                # Only the PNG decoder ever sees the bytes.
                with Image.open(io.BytesIO(data), formats=("PNG",)) as probe:
                    width, height = probe.size
                    animated = bool(getattr(probe, "is_animated", False))
                    mode = probe.mode
                    icc = probe.info.get("icc_profile")
                    probe.verify()
                with Image.open(io.BytesIO(data), formats=("PNG",)) as image:
                    image.load()
                    rgba = image.convert("RGBA") if image.mode != "RGBA" else image
                    alpha = rgba.getchannel("A")
                    slot_transparency = tuple(
                        _transparent_ratio(alpha, slot) for slot in template.slots
                    )
        except FrameValidationError:
            raise
        except (OSError, ValueError, SyntaxError, Image.DecompressionBombError) as exc:
            raise FrameValidationError(["The frame must be a valid PNG file."]) from exc

        if animated:
            problems.append("The frame must not be animated.")
        if width != template.width_px or height != template.height_px:
            problems.append(
                f"The frame must be exactly {template.width_px} x {template.height_px} px "
                f"for {template.name}; this file is {width} x {height} px."
            )
        if mode in ("L", "LA", "1", "I", "F", "I;16"):
            problems.append(
                "Grayscale frames are not accepted; save the frame in sRGB colour with "
                "transparency (RGBA)."
            )
        elif mode == "CMYK":
            problems.append("CMYK frames are not accepted; save the frame in sRGB colour.")
        elif mode != "RGBA":
            problems.append(
                "The frame must have a transparent background: save it as a PNG with an alpha "
                f"channel (RGBA); this file is mode {mode}."
            )
        for slot, ratio in zip(template.slots, slot_transparency, strict=True):
            if ratio < rules.slot_min_transparency:
                problems.append(
                    f"Photo {slot.index} area must be at least "
                    f"{_percent(rules.slot_min_transparency)} transparent; it is "
                    f"{_percent(ratio)} transparent. Erase that rectangle "
                    f"(x={slot.rect.x}, y={slot.rect.y}, w={slot.rect.w}, h={slot.rect.h} px)."
                )
        if problems:
            raise FrameValidationError(problems)

        return FrameValidationReport(
            warnings=_colour_warnings(icc),
            width=width,
            height=height,
            slot_transparency=slot_transparency,
        )


def _transparent_ratio(alpha: Image.Image, slot: SlotDefinition) -> float:
    rect = slot.rect
    box = (rect.x, rect.y, rect.x + rect.w, rect.y + rect.h)
    region = alpha.crop(box)
    histogram = region.histogram()
    total = rect.w * rect.h
    transparent = sum(histogram[: TRANSPARENT_ALPHA + 1])
    return 0.0 if total == 0 else transparent / total


def _colour_warnings(icc: bytes | None) -> tuple[str, ...]:
    """sRGB and untagged files are fine; another RGB profile is converted when rendering."""
    if not icc:
        return ()
    try:
        profile = ImageCms.getOpenProfile(io.BytesIO(icc))
        description = (ImageCms.getProfileDescription(profile) or "").strip()
    except (ImageCms.PyCMSError, OSError):
        return ("The colour profile could not be read; it will be ignored when printing.",)
    if any(hint in description.lower() for hint in SRGB_HINTS):
        return ()
    return (
        f"The frame uses the colour profile '{description}'. It will be converted to sRGB when "
        "photos are rendered, so colours may shift slightly.",
    )
