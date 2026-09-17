"""Template domain: immutable, self-validating value objects and ports (no framework imports)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import StrEnum
from math import gcd
from typing import Protocol


class TemplateError(Exception):
    """A template definition violates an invariant."""


class TemplateNotFoundError(LookupError):
    def __init__(self, key: str, version: int | None) -> None:
        suffix = "" if version is None else f" v{version}"
        super().__init__(f"template not found: {key}{suffix}")


class Orientation(StrEnum):
    PORTRAIT = "portrait"
    LANDSCAPE = "landscape"


@dataclass(frozen=True)
class Rect:
    x: int
    y: int
    w: int
    h: int

    @property
    def right(self) -> int:
        return self.x + self.w

    @property
    def bottom(self) -> int:
        return self.y + self.h

    def overlaps(self, other: Rect) -> bool:
        return not (
            self.right <= other.x
            or other.right <= self.x
            or self.bottom <= other.y
            or other.bottom <= self.y
        )

    def inside(self, width: int, height: int) -> bool:
        return self.x >= 0 and self.y >= 0 and self.right <= width and self.bottom <= height


@dataclass(frozen=True)
class SlotDefinition:
    index: int
    rect: Rect
    fit: str = "cover"
    anchor: str = "center"

    @property
    def aspect_label(self) -> str:
        divisor = gcd(self.rect.w, self.rect.h)
        return f"{self.rect.w // divisor}:{self.rect.h // divisor}"


@dataclass(frozen=True)
class FrameRules:
    format: str
    mode: str
    exact_size: bool
    max_bytes: int
    color: str
    slot_min_transparency: float
    animated: bool


@dataclass(frozen=True)
class PhotoTemplate:
    """A versioned layout. `output_capture_groups[i]` lists the 1-based captures of output i+1."""

    key: str
    version: int
    name: str
    width_in: float
    height_in: float
    dpi: int
    width_px: int
    height_px: int
    orientation: Orientation
    photos_per_output: int
    captures_per_session: int
    outputs_per_session: int
    output_capture_groups: tuple[tuple[int, ...], ...]
    slots: tuple[SlotDefinition, ...]
    safe_area_inset: int
    bleed: int
    branding_area: Rect | None
    frame_rules: FrameRules

    def __post_init__(self) -> None:
        self.validate()

    @property
    def safe_area(self) -> Rect:
        inset = self.safe_area_inset
        return Rect(inset, inset, self.width_px - 2 * inset, self.height_px - 2 * inset)

    def validate(self) -> None:
        problems: list[str] = []
        if round(self.width_in * self.dpi) != self.width_px:
            problems.append(f"width {self.width_px}px != {self.width_in}in x {self.dpi}dpi")
        if round(self.height_in * self.dpi) != self.height_px:
            problems.append(f"height {self.height_px}px != {self.height_in}in x {self.dpi}dpi")
        expected_orientation = (
            Orientation.PORTRAIT if self.height_px >= self.width_px else Orientation.LANDSCAPE
        )
        if self.orientation is not expected_orientation:
            problems.append(f"orientation should be {expected_orientation}")
        indexes = [slot.index for slot in self.slots]
        if indexes != list(range(1, len(self.slots) + 1)):
            problems.append(f"slot indexes must be 1..n in order, got {indexes}")
        if len(self.slots) != self.photos_per_output:
            problems.append(
                f"{len(self.slots)} slots but photos_per_output={self.photos_per_output}"
            )
        for slot in self.slots:
            if (
                slot.rect.w <= 0
                or slot.rect.h <= 0
                or not slot.rect.inside(self.width_px, self.height_px)
            ):
                problems.append(f"slot {slot.index} is outside the canvas")
            if slot.fit != "cover" or slot.anchor != "center":
                problems.append(f"slot {slot.index}: only fit=cover, anchor=center supported")
        for i, first in enumerate(self.slots):
            for second in self.slots[i + 1 :]:
                if first.rect.overlaps(second.rect):
                    problems.append(f"slots {first.index} and {second.index} overlap")
        if len(self.output_capture_groups) != self.outputs_per_session:
            problems.append("output_capture_groups must have outputs_per_session entries")
        flattened = [c for group in self.output_capture_groups for c in group]
        if sorted(flattened) != list(range(1, self.captures_per_session + 1)):
            problems.append(
                "every capture 1..captures_per_session must be used exactly once across outputs"
            )
        if any(len(group) != self.photos_per_output for group in self.output_capture_groups):
            problems.append("each output must use exactly photos_per_output captures")
        if not 0 <= self.safe_area_inset * 2 < min(self.width_px, self.height_px):
            problems.append("safe area inset is invalid")
        if self.branding_area is not None and not self.branding_area.inside(
            self.width_px, self.height_px
        ):
            problems.append("branding area is outside the canvas")
        if problems:
            raise TemplateError(f"{self.key} v{self.version}: " + "; ".join(problems))

    def frame_requirements(self) -> list[str]:
        """Plain-language checklist for frame designers (shown by the spec API and guide image)."""
        rules = self.frame_rules
        safe = self.safe_area
        lines = [
            f"File: {rules.format} with transparency ({rules.mode}), not animated.",
            f"Size: exactly {self.width_px} x {self.height_px} px "
            f"({_inches(self.width_in)} x {_inches(self.height_in)} in at {self.dpi} DPI).",
            f"Color: {rules.color}. Maximum file size {rules.max_bytes // (1024 * 1024)} MB.",
            f"Photo areas must be at least {round(rules.slot_min_transparency * 100)}% "
            "transparent:",
        ]
        lines += [
            f"  Photo {slot.index}: x={slot.rect.x}, y={slot.rect.y}, "
            f"w={slot.rect.w}, h={slot.rect.h} px ({slot.aspect_label}, photo is center-cropped)."
            for slot in self.slots
        ]
        lines.append(
            f"Safe area: keep text and logos inside x {safe.x}-{safe.right}, "
            f"y {safe.y}-{safe.bottom} px ({self.safe_area_inset} px margin)."
        )
        if self.branding_area is not None:
            area = self.branding_area
            lines.append(
                f"Branding area: x={area.x}, y={area.y}, w={area.w}, h={area.h} px "
                "(free space for event name or logo)."
            )
        lines.append(f"Bleed: {self.bleed} px.")
        if self.outputs_per_session > 1:
            groups = ", ".join(
                f"output {i + 1} uses captures {'-'.join(map(str, (g[0], g[-1])))}"
                for i, g in enumerate(self.output_capture_groups)
            )
            lines.append(
                f"Each session captures {self.captures_per_session} photos and produces "
                f"{self.outputs_per_session} outputs with this frame: {groups}."
            )
        return lines


def _inches(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else f"{value:g}"


class TemplateRepository(ABC):
    """Read-only source of versioned template definitions."""

    @abstractmethod
    def all(self) -> list[PhotoTemplate]:
        """Every version of every template."""

    def latest(self) -> list[PhotoTemplate]:
        newest: dict[str, PhotoTemplate] = {}
        for template in self.all():
            current = newest.get(template.key)
            if current is None or template.version > current.version:
                newest[template.key] = template
        return [newest[key] for key in sorted(newest)]

    def get(self, key: str, version: int | None = None) -> PhotoTemplate:
        candidates = [t for t in self.all() if t.key == key]
        if version is not None:
            candidates = [t for t in candidates if t.version == version]
        if not candidates:
            raise TemplateNotFoundError(key, version)
        return max(candidates, key=lambda t: t.version)


class TemplateArtist(Protocol):
    """Draws specification images for a template (PNG bytes, canvas size, template DPI)."""

    def blank_png(self, template: PhotoTemplate) -> bytes: ...

    def guide_png(self, template: PhotoTemplate) -> bytes: ...
