"""Kiosk pairing use cases."""

from __future__ import annotations

from photobooth.modules.kiosk.domain import (
    PairingOutcome,
    PairingPort,
    PairingResult,
    RotationRejectedError,
)


class KioskPairingService:
    def __init__(self, pairing: PairingPort) -> None:
        self._pairing = pairing

    def pair(self, code: str | None) -> PairingResult:
        credential = self._pairing.consume(code)
        if credential is None:
            return PairingResult(outcome=PairingOutcome.REJECTED)
        return PairingResult(outcome=PairingOutcome.PAIRED, device_credential=credential)

    def rotate_code(self) -> None:
        """Publish a new code to the runtime file. The code never leaves the server otherwise."""
        if not self._pairing.rotate():
            raise RotationRejectedError
