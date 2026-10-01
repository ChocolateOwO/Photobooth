"""Delivery domain: the guest's take-home link for a finished visit.

The link carries a random 256-bit token. The database keeps only its SHA-256, never the token
itself; the plaintext exists in the QR code the booth shows and, for a short while, in this
process's memory so a reload of the booth screen shows the same code. After a restart the booth
can not show the old code again: showing the link issues a new one and revokes the old.

A guest who asks for anything that is not theirs, expired, revoked or simply wrong gets the same
answer as for a path that does not exist, so nothing about other visits can be learned.
"""

from __future__ import annotations

import hashlib
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

# 32 random bytes in URL-safe base64 without padding.
TOKEN_BYTES = 32
TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]{43}$")
# How long the plaintext may stay in memory for the booth screen to show the same code again.
CACHE_LIFETIME = timedelta(minutes=30)
# Plan default until the retention policy decides it (PROVISIONAL: links 7 days).
DEFAULT_LINK_LIFETIME = timedelta(days=7)


class DeliveryNotFoundError(Exception):
    """Uniform "not found": unknown, expired or revoked link, or a file that is not the guest's."""

    def __init__(self) -> None:
        super().__init__("not found")


class DeliveryUnavailableError(Exception):
    """The visit has no finished photos to deliver."""


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def well_formed(token: str) -> bool:
    return bool(TOKEN_PATTERN.fullmatch(token))


@dataclass(frozen=True)
class DeliveryToken:
    id: str
    session_id: str
    token_hash: str
    created_at: datetime
    expires_at: datetime
    revoked_at: datetime | None = None
    opened_at: datetime | None = None
    download_count: int = 0

    def usable(self, now: datetime) -> bool:
        return self.revoked_at is None and now < self.expires_at


@dataclass(frozen=True)
class DeliverableFile:
    """One finished photo the link hands out (nothing about files, frames or storage)."""

    output_id: str
    output_index: int
    width: int
    height: int
    byte_size: int
    sha256: str
    rendered_at: datetime


@dataclass(frozen=True)
class IssuedLink:
    token_id: str
    url: str
    expires_at: datetime
    qr_svg: str


@dataclass(frozen=True)
class OpenedLink:
    """What a guest who holds a valid link may see."""

    token: DeliveryToken
    files: tuple[DeliverableFile, ...]


class DeliveryTokenRepository(ABC):
    """Every method is one transaction."""

    @abstractmethod
    def current(self, session_id: str) -> DeliveryToken | None:
        """The visit's link that is not revoked (it may have expired)."""

    @abstractmethod
    def replace(self, token: DeliveryToken, at: datetime) -> None:
        """Revoke every other link of the visit and record this one, together."""

    @abstractmethod
    def by_hash(self, token_hash: str) -> DeliveryToken | None: ...

    @abstractmethod
    def mark_opened(self, token_id: str, at: datetime) -> None:
        """Record the first time the guest opened the link."""

    @abstractmethod
    def count_download(self, token_id: str) -> None: ...

    @abstractmethod
    def revoke_session(self, session_id: str, at: datetime) -> list[str]:
        """Revoke the visit's links; returns the ids of the links that were still live."""


class DeliveredOutputs(Protocol):
    """The finished photos of a visit (from the sessions module)."""

    def files(self, session_id: str) -> list[DeliverableFile]: ...

    def read(self, session_id: str, output_id: str) -> bytes: ...


class LinkAddress(Protocol):
    """Where guests' phones reach the delivery listener, e.g. http://192.168.1.20:8113."""

    def base_url(self) -> str: ...


class QrEncoder(Protocol):
    def svg(self, text: str) -> str: ...


class LinkPolicy(Protocol):
    """How long a new link stays valid (the retention policy decides)."""

    def lifetime(self) -> timedelta: ...


class Clock(Protocol):
    def now(self) -> datetime: ...
