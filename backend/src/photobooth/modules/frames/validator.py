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
_SRGB_PROFILE = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB"))


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
                # Only the PNG decoder ever sees these bytes. The header is checked first, so a
                # wrong canvas size is refused before any pixel data is decoded.
                with Image.open(io.BytesIO(data), formats=("PNG",)) as probe:
                    width, height = probe.size
                    if width != template.width_px or height != template.height_px:
                        raise FrameValidationError(
                            [
                                f"The frame must be exactly {template.width_px} x "
                                f"{template.height_px} px for {template.name}; this file is "
                                f"{width} x {height} px."
                            ]
                        )
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
                    colour_problem, colour_warnings = _check_colour(icc, rgba)
        except FrameValidationError:
            raise
        except (
            OSError,
            ValueError,
            SyntaxError,
            Image.DecompressionBombError,
            Image.DecompressionBombWarning,
        ) as exc:
            raise FrameValidationError(["The frame must be a valid PNG file."]) from exc

        if animated:
            problems.append("The frame must not be animated.")
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
        if colour_problem is not None:
            problems.append(colour_problem)
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
            warnings=colour_warnings,
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


def _check_colour(icc: bytes | None, rgba: Image.Image) -> tuple[str | None, tuple[str, ...]]:
    """Untagged files count as sRGB. A tagged file must survive the very conversion the renderer
    performs later (ImageCms, RGB input -> sRGB); otherwise its previews and printed outputs would
    fail after it was accepted, so such a profile is refused here with a plain reason.
    """
    if not icc:
        return None, ()
    unusable = (
        "The frame has a colour profile this booth can not convert. Save the frame again in sRGB "
        "(or without a colour profile)."
    )
    try:
        profile = ImageCms.getOpenProfile(io.BytesIO(icc))
        description = (ImageCms.getProfileDescription(profile) or "").strip()
    except (ImageCms.PyCMSError, OSError):
        return unusable, ()
    try:
        # One pixel is enough to prove the transform the renderer needs can be built.
        converted = ImageCms.profileToProfile(
            rgba.crop((0, 0, 1, 1)).convert("RGB"),
            profile,
            _SRGB_PROFILE,
            renderingIntent=ImageCms.Intent.RELATIVE_COLORIMETRIC,
            outputMode="RGB",
        )
    except (OSError, ValueError, ImageCms.PyCMSError):
        return unusable, ()
    if converted is None:
        return unusable, ()
    if any(hint in description.lower() for hint in SRGB_HINTS):
        return None, ()
    return None, (
        f"The frame uses the colour profile '{description}'. It will be converted to sRGB when "
        "photos are rendered, so colours may shift slightly.",
    )
