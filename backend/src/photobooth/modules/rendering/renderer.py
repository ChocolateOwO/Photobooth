"""Pillow infrastructure: final server-side renderer and synthetic sample photos."""

from __future__ import annotations

import io
import warnings

from PIL import Image, ImageCms, ImageDraw, ImageFont, ImageOps

from photobooth.modules.rendering.domain import (
    JPEG_MEDIA_TYPE,
    PhotoRenderer,
    RenderedOutput,
    RenderError,
    RenderJob,
)

MAX_INPUT_PIXELS = 50_000_000  # decompression-bomb guard for captures and frames
JPEG_QUALITY = 95
CANVAS_BACKGROUND = (255, 255, 255)
_SRGB_PROFILE = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB"))
_SRGB_ICC = _SRGB_PROFILE.tobytes()


def to_srgb(
    image: Image.Image, what: str, keep_alpha: bool, icc: bytes | None = None
) -> Image.Image:
    """Color-manage an input into sRGB (RGB, or RGBA when `keep_alpha`).

    Embedded ICC profiles (e.g. Adobe RGB, Display P3, gray, tagged CMYK) are converted, not just
    relabelled; untagged RGB/gray is treated as sRGB; untagged CMYK is rejected.
    """
    has_alpha = image.mode in ("RGBA", "LA", "PA") or (
        image.mode == "P" and "transparency" in image.info
    )
    alpha = image.convert("RGBA").getchannel("A") if (keep_alpha and has_alpha) else None
    icc = icc or image.info.get("icc_profile")
    if icc:
        try:
            source = ImageCms.ImageCmsProfile(io.BytesIO(icc))
        except (OSError, ImageCms.PyCMSError) as exc:
            raise RenderError(f"{what} has an unreadable ICC profile: {exc}") from exc
        base = image
        if image.mode in ("RGBA", "P", "PA"):
            base = image.convert("RGB")
        elif image.mode == "LA":
            base = image.convert("L")
        try:
            converted = ImageCms.profileToProfile(
                base,
                source,
                _SRGB_PROFILE,
                renderingIntent=ImageCms.Intent.RELATIVE_COLORIMETRIC,
                outputMode="RGB",
            )
        except (OSError, ValueError, ImageCms.PyCMSError) as exc:
            raise RenderError(
                f"{what} has an ICC profile that does not match its pixels: {exc}"
            ) from exc
        assert converted is not None
        result = converted
    elif image.mode == "CMYK":
        raise RenderError(f"{what} is CMYK without an ICC profile; provide sRGB or a tagged image")
    else:
        result = image.convert("RGB")
    if alpha is not None:
        result = result.convert("RGBA")
        result.putalpha(alpha)
    elif keep_alpha:
        result = result.convert("RGBA")
    return result


def _open(data: bytes, what: str) -> Image.Image:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            image = Image.open(io.BytesIO(data))
            if image.width * image.height > MAX_INPUT_PIXELS:
                raise RenderError(f"{what} is too large ({image.width}x{image.height})")
            image.load()
    except RenderError:
        raise
    except (
        OSError,
        ValueError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ) as exc:
        raise RenderError(f"{what} is not a readable image: {exc}") from exc
    return image


class PillowPhotoRenderer(PhotoRenderer):
    """Cover-crops each capture into its slot, overlays the frame, exports sRGB JPEG with DPI."""

    def render(self, job: RenderJob) -> RenderedOutput:
        template = job.template
        canvas = Image.new("RGB", (template.width_px, template.height_px), CANVAS_BACKGROUND)

        for assignment in job.plan.assignments:
            capture_id = assignment.capture.capture_id
            if capture_id not in job.images:
                raise RenderError(f"missing image for capture {capture_id}")
            opened = _open(job.images[capture_id], f"capture {capture_id}")
            photo = to_srgb(
                ImageOps.exif_transpose(opened),
                f"capture {capture_id}",
                keep_alpha=False,
                icc=opened.info.get("icc_profile"),  # read before any transpose copy
            )
            if job.mirror:
                photo = ImageOps.mirror(photo)
            rect = assignment.slot.rect
            fitted = ImageOps.fit(
                photo, (rect.w, rect.h), method=Image.Resampling.LANCZOS, centering=(0.5, 0.5)
            )
            canvas.paste(fitted, (rect.x, rect.y))

        if job.frame_png is not None:
            frame = _open(job.frame_png, "frame")
            if frame.size != (template.width_px, template.height_px):
                raise RenderError(
                    f"frame must be {template.width_px}x{template.height_px}, got "
                    f"{frame.width}x{frame.height}"
                )
            frame_rgba = to_srgb(frame, "frame", keep_alpha=True)
            canvas = Image.alpha_composite(canvas.convert("RGBA"), frame_rgba).convert("RGB")

        buffer = io.BytesIO()
        canvas.save(
            buffer,
            format="JPEG",
            quality=JPEG_QUALITY,
            subsampling=0,
            dpi=(template.dpi, template.dpi),
            icc_profile=_SRGB_ICC,
        )
        return RenderedOutput(
            output_index=job.plan.output_index,
            data=buffer.getvalue(),
            media_type=JPEG_MEDIA_TYPE,
            width=template.width_px,
            height=template.height_px,
            dpi=template.dpi,
            capture_ids=job.plan.capture_ids,
        )


SAMPLE_COLORS = (
    (231, 76, 60),
    (46, 204, 113),
    (52, 152, 219),
    (241, 196, 15),
    (155, 89, 182),
    (26, 188, 156),
)


class PillowSampleImageFactory:
    """16:9 webcam-like placeholder photos: a solid color per shot with a large shot number."""

    def sample_capture(self, shot_index: int) -> bytes:
        color = SAMPLE_COLORS[(shot_index - 1) % len(SAMPLE_COLORS)]
        image = Image.new("RGB", (1280, 720), color)
        draw = ImageDraw.Draw(image)
        font = ImageFont.load_default(size=360)
        text = str(shot_index)
        box = draw.textbbox((0, 0), text, font=font)
        position = ((1280 - (box[2] - box[0])) / 2 - box[0], (720 - (box[3] - box[1])) / 2 - box[1])
        draw.text(position, text, font=font, fill=(255, 255, 255))
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=90)
        return buffer.getvalue()
