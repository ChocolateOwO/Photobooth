"""Pillow infrastructure: final server-side renderer and synthetic sample photos."""

from __future__ import annotations

import functools
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

    def sample_photo(self, shot_index: int) -> bytes:
        return sample_photo_bytes(shot_index)

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


# Illustrated stand-ins for real guest photos: warm backdrops with friendly silhouettes. Used for
# every frame preview (admin and participants); no real person is ever shown.
_PHOTO_SCENES: tuple[tuple[tuple[int, int, int], tuple[int, int, int]], ...] = (
    ((255, 196, 150), (255, 128, 128)),
    ((150, 205, 255), (120, 150, 240)),
    ((190, 240, 200), (110, 190, 170)),
    ((255, 225, 150), (240, 150, 90)),
    ((220, 190, 255), (160, 120, 230)),
    ((255, 205, 225), (225, 130, 175)),
)
_PEOPLE = ((96, 64, 58), (70, 52, 60), (120, 86, 70), (60, 60, 82))
_SHIRTS = ((250, 250, 250), (40, 60, 110), (200, 70, 90), (60, 140, 120), (240, 180, 60))


@functools.lru_cache(maxsize=16)
def sample_photo_bytes(shot_index: int) -> bytes:
    """A 1280x720 illustrated 'photo' for shot N (deterministic), with a small shot badge."""
    top, bottom = _PHOTO_SCENES[(shot_index - 1) % len(_PHOTO_SCENES)]
    width, height = 1280, 720
    column = Image.new("RGB", (1, height))
    for y in range(height):
        t = y / (height - 1)
        column.putpixel(
            (0, y), tuple(round(a + (b - a) * t) for a, b in zip(top, bottom, strict=True))
        )
    image = column.resize((width, height)).convert("RGBA")
    glow = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    gdraw = ImageDraw.Draw(glow)
    for i in range(9):  # soft bokeh lights
        x = (i * 173 + shot_index * 97) % width
        y = (i * 89 + shot_index * 53) % (height // 2)
        r = 30 + (i * 17 + shot_index * 11) % 50
        gdraw.ellipse((x - r, y - r, x + r, y + r), fill=(255, 255, 255, 60))
    image.alpha_composite(glow)
    draw = ImageDraw.Draw(image)
    # Portrait slots keep only the middle of the frame, so everyone stands near the centre.
    people = 1 + (shot_index % 3)
    for p in range(people):
        cx = width / 2 + (p - (people - 1) / 2) * 175
        scale = 0.72 - 0.06 * abs(p - (people - 1) / 2)
        head = 92 * scale
        shoulders_top = height - 300 * scale
        skin = _PEOPLE[(shot_index + p) % len(_PEOPLE)]
        shirt = _SHIRTS[(shot_index * 2 + p) % len(_SHIRTS)]
        draw.rounded_rectangle(
            (cx - 190 * scale, shoulders_top, cx + 190 * scale, height + 60),
            radius=round(150 * scale),
            fill=shirt,
        )
        draw.rectangle(
            (cx - 40 * scale, shoulders_top - 60 * scale, cx + 40 * scale, shoulders_top + 10),
            fill=skin,
        )
        head_cy = shoulders_top - 60 * scale - head * 0.8
        draw.ellipse((cx - head, head_cy - head, cx + head, head_cy + head), fill=skin)
        # a happy face: eyes and smile
        eye = 11 * scale
        for dx in (-32, 32):
            draw.ellipse(
                (
                    cx + dx * scale - eye,
                    head_cy - 12 * scale - eye,
                    cx + dx * scale + eye,
                    head_cy - 12 * scale + eye,
                ),
                fill=(35, 30, 35),
            )
        smile = 44 * scale
        draw.arc(
            (cx - smile, head_cy - 8 * scale, cx + smile, head_cy + 46 * scale),
            start=20,
            end=160,
            fill=(35, 30, 35),
            width=max(4, round(8 * scale)),
        )
        hair = (40 + (p * 30) % 90, 30 + (p * 20) % 60, 25)
        draw.chord(
            (cx - head * 1.02, head_cy - head * 1.08, cx + head * 1.02, head_cy + head * 0.6),
            start=180,
            end=360,
            fill=hair,
        )
    # shot badge (slot order) in the corner
    badge = 44
    left = width / 2 - 230  # inside the centre that portrait slots keep
    draw.ellipse((left, 24, left + badge * 2, 24 + badge * 2), fill=(255, 255, 255, 220))
    font = ImageFont.load_default(size=56)
    text = str(shot_index)
    box = draw.textbbox((0, 0), text, font=font)
    draw.text(
        (
            left + badge - (box[2] - box[0]) / 2 - box[0],
            24 + badge - (box[3] - box[1]) / 2 - box[1],
        ),
        text,
        font=font,
        fill=(40, 40, 50),
    )
    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, format="JPEG", quality=88)
    return buffer.getvalue()
