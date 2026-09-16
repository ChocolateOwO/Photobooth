"""Kiosk pairing domain: outcomes and the ports the service depends on."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol


class PairingOutcome(StrEnum):
    PAIRED = "paired"
    REJECTED = "rejected"


@dataclass(frozen=True)
class PairingResult:
    outcome: PairingOutcome
    device_credential: str | None = None


class PairingPort(Protocol):
    """Issues pairing codes out-of-band and exchanges a valid code for a credential."""

    def rotate(self) -> bool:
        """Publish a new code; False when rate limited."""

    def consume(self, code: str | None) -> str | None: ...


class RotationRejectedError(Exception):
    """Rotation was refused (rate limited)."""
