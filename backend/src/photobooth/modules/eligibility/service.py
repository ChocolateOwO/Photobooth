"""The eligibility check the MVP runs: everybody at the booth may take photos."""

from __future__ import annotations

from photobooth.modules.eligibility.domain import Decision


class AllowAllEligibility:
    """Allows every device. Records which check answered, so a later real check is visible."""

    name = "allow_all"

    def check(self, device_id: str, profile_id: str) -> Decision:
        return Decision(allowed=True, details={"check": self.name})
