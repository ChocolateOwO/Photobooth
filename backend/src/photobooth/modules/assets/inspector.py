"""Pillow-based ImageInspector: decode untrusted uploads defensively."""

from __future__ import annotations

import io
import warnings

from PIL import Image

from photobooth.modules.assets.domain import (
    ALLOWED_FORMATS,
    AssetValidationError,
    ImageFacts,
    UploadLimits,
)

ALLOWED_MODES = frozenset({"RGB", "RGBA", "L", "LA", "P"})
# Only these decoders ever see untrusted bytes (no EPS/PSD/ICO/... plugin is tried).
DECODERS = tuple(ALLOWED_FORMATS)


class PillowImageInspector:
    def inspect(self, data: bytes, limits: UploadLimits) -> ImageFacts:
        if not data:
            raise AssetValidationError("The file is empty.")
        if len(data) > limits.max_bytes:
            raise AssetValidationError(
                f"The file is too large ({len(data)} bytes); the limit is {limits.max_bytes} bytes."
            )
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(io.BytesIO(data), formats=DECODERS) as probe:
                    image_format = probe.format or ""
                    width, height = probe.size
                    if image_format not in ALLOWED_FORMATS:
                        raise AssetValidationError(
                            "Only PNG or JPEG images are accepted "
                            f"(got {image_format or 'unknown'})."
                        )
                    self._check_size(width, height, limits)
                    animated = bool(getattr(probe, "is_animated", False))
                    probe.verify()
                with Image.open(io.BytesIO(data), formats=DECODERS) as image:
                    image.load()
                    mode = image.mode
                    has_alpha = mode in ("RGBA", "LA") or (
                        mode == "P" and "transparency" in image.info
                    )
        except AssetValidationError:
            raise
        except (
            OSError,
            ValueError,
            SyntaxError,
            Image.DecompressionBombError,
            Image.DecompressionBombWarning,
        ) as exc:
            raise AssetValidationError("The file is not a valid PNG or JPEG image.") from exc
        if animated:
            raise AssetValidationError("Animated images are not accepted.")
        if mode not in ALLOWED_MODES:
            raise AssetValidationError(
                f"Image color mode {mode} is not supported; save it as RGB or RGBA."
            )
        return ImageFacts(
            format=image_format, width=width, height=height, has_alpha=has_alpha, animated=False
        )

    @staticmethod
    def _check_size(width: int, height: int, limits: UploadLimits) -> None:
        if width < limits.min_width or height < limits.min_height:
            raise AssetValidationError(
                f"The image is too small ({width} x {height} px); minimum is "
                f"{limits.min_width} x {limits.min_height} px."
            )
        if width > limits.max_width or height > limits.max_height:
            raise AssetValidationError(
                f"The image is too large ({width} x {height} px); maximum is "
                f"{limits.max_width} x {limits.max_height} px."
            )
