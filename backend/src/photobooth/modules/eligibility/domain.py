"""Who may start a booth session.

The MVP lets everyone in; a later phase plugs a real check (Reconize) in behind this same port,
so nothing in the booth has to change when it arrives.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class Decision:
    allowed: bool
    reason: str | None = None
    details: Mapping[str, str] | None = None


class EligibilityCheck(Protocol):
    def check(self, device_id: str, profile_id: str) -> Decision: ...
