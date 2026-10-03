"""Delivery use cases: issue the take-home link, and hand a guest exactly their own photos."""

from __future__ import annotations

import secrets
import threading
import time
import uuid
from collections import deque
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from photobooth.modules.delivery.domain import (
    CACHE_LIFETIME,
    DEFAULT_LINK_LIFETIME,
    TOKEN_BYTES,
    Clock,
    DeliverableFile,
    DeliveredOutputs,
    DeliveryNotFoundError,
    DeliveryToken,
    DeliveryTokenRepository,
    DeliveryUnavailableError,
    IssuedLink,
    LinkActivity,
    LinkAddress,
    LinkFacts,
    LinkPolicy,
    OpenedLink,
    QrEncoder,
    hash_token,
    well_formed,
)


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


class FixedLinkPolicy:
    def __init__(self, lifetime: timedelta = DEFAULT_LINK_LIFETIME) -> None:
        self._lifetime = lifetime

    def lifetime(self, session_id: str) -> timedelta:
        return self._lifetime


class NoLinkActivity:
    def record(self, kind: str, session_id: str, /, **facts: str | int | bool) -> None:
        return None


class DeliveryService:
    """The guest's link: made once per visit, shown again from memory, checked on every use."""

    def __init__(
        self,
        repository: DeliveryTokenRepository,
        outputs: DeliveredOutputs,
        address: LinkAddress,
        qr: QrEncoder,
        policy: LinkPolicy | None = None,
        clock: Clock | None = None,
        new_token: Callable[[], str] = lambda: secrets.token_urlsafe(TOKEN_BYTES),
        activity: LinkActivity | None = None,
    ) -> None:
        self._repository = repository
        self._outputs = outputs
        self._address = address
        self._qr = qr
        self._policy = policy or FixedLinkPolicy()
        self._clock = clock or SystemClock()
        self._new_token = new_token
        self._activity = activity or NoLinkActivity()
        # token id -> (plaintext, keep until). Never written anywhere; gone at restart.
        self._plaintext: dict[str, tuple[str, datetime]] = {}
        self._lock = threading.Lock()

    # ---- the booth side ----------------------------------------------------------------------

    def ensure(self, session_id: str) -> IssuedLink:
        """The visit's current link, or a new one that replaces it.

        The caller holds the visit's lock, so this runs once at a time per visit: a reload shows
        the same code while it is remembered; otherwise a new code is made and the old revoked.
        """
        if not self._outputs.files(session_id):
            raise DeliveryUnavailableError("this visit has no finished photos")
        now = self._clock.now()
        current = self._repository.current(session_id)
        if current is not None and current.usable(now):
            remembered = self._remembered(current.id, now)
            if remembered is not None:
                return self._link(current, remembered)
        plaintext = self._new_token()
        token = DeliveryToken(
            id=str(uuid.uuid4()),
            session_id=session_id,
            token_hash=hash_token(plaintext),
            created_at=now,
            expires_at=now + self._policy.lifetime(session_id),
        )
        self._repository.replace(token, now)
        with self._lock:
            if current is not None:
                self._plaintext.pop(current.id, None)
            self._plaintext[token.id] = (plaintext, min(token.expires_at, now + CACHE_LIFETIME))
            self._forget_stale(now)
        return self._link(token, plaintext, new=True, renewed=current is not None)

    def forget_expired(self) -> int:
        """Drop every remembered link whose time is up, whether or not anyone asks again.
        Runs from the booth's periodic upkeep, so no plaintext outlives its deadline by long."""
        now = self._clock.now()
        with self._lock:
            before = len(self._plaintext)
            self._forget_stale(now)
            return before - len(self._plaintext)

    def revoke(self, session_id: str) -> int:
        """End every link of a visit (the organizer's decision, or retention)."""
        revoked = self._repository.revoke_session(session_id, self._clock.now())
        with self._lock:
            for token_id in revoked:
                self._plaintext.pop(token_id, None)
        return len(revoked)

    # ---- the guest side ----------------------------------------------------------------------

    def open(self, token: str) -> OpenedLink:
        """The guest's landing page: their finished photos, in order."""
        row = self._valid(token)
        files = tuple(self._outputs.files(row.session_id))
        if not files:
            raise DeliveryNotFoundError()
        if row.opened_at is None and self._repository.mark_opened(row.id, self._clock.now()):
            self._activity.record("qr_opened", row.session_id)
        return OpenedLink(token=row, files=files)

    def file(self, token: str, output_id: str) -> tuple[DeliverableFile, bytes]:
        """One photo, only if it belongs to the link's own visit."""
        row = self._valid(token)
        for candidate in self._outputs.files(row.session_id):
            if candidate.output_id == output_id:
                try:
                    return candidate, self._outputs.read(row.session_id, output_id)
                except Exception as exc:  # a vanished file is "not found" for a guest
                    raise DeliveryNotFoundError() from exc
        raise DeliveryNotFoundError()

    def everything(self, token: str) -> tuple[DeliveryToken, list[DeliverableFile]]:
        """Everything the link hands out, for Download All (read one file at a time after)."""
        row = self._valid(token)
        files = self._outputs.files(row.session_id)
        if not files:
            raise DeliveryNotFoundError()
        return row, files

    def read(self, token: DeliveryToken, output_id: str) -> bytes:
        return self._outputs.read(token.session_id, output_id)

    def count_download(self, token: DeliveryToken, output_index: int | None = None) -> None:
        """One photo saved (its position), or Download All (no position)."""
        self._repository.count_download(token.id)
        if output_index is None:
            self._activity.record("download", token.session_id, kind="zip")
        else:
            self._activity.record("download", token.session_id, kind="file", output=output_index)

    def facts(self, session_ids: list[str]) -> dict[str, LinkFacts]:
        """What became of each visit's links, for History and Statistics. Never a token."""
        return self._repository.facts(session_ids)

    # ---- internals ---------------------------------------------------------------------------

    def _valid(self, token: str) -> DeliveryToken:
        if not well_formed(token):
            raise DeliveryNotFoundError()
        row = self._repository.by_hash(hash_token(token))
        if row is None or not row.usable(self._clock.now()):
            raise DeliveryNotFoundError()
        return row

    def _link(
        self, token: DeliveryToken, plaintext: str, *, new: bool = False, renewed: bool = False
    ) -> IssuedLink:
        url = f"{self._address.base_url()}/d/{plaintext}"
        return IssuedLink(
            token_id=token.id,
            url=url,
            expires_at=token.expires_at,
            qr_svg=self._qr.svg(url),
            new=new,
            renewed=renewed,
        )

    def _remembered(self, token_id: str, now: datetime) -> str | None:
        with self._lock:
            entry = self._plaintext.get(token_id)
            if entry is None or entry[1] <= now:
                self._plaintext.pop(token_id, None)
                return None
            return entry[0]

    def _forget_stale(self, now: datetime) -> None:
        for token_id in [key for key, entry in self._plaintext.items() if entry[1] <= now]:
            del self._plaintext[token_id]


class RequestBudget:
    """How many delivery requests one client address may make per minute (in memory).

    Guessing a 256-bit link is hopeless anyway; this only stops one phone from keeping the booth
    busy building ZIP files.
    """

    def __init__(
        self,
        limit: int,
        window_seconds: float = 60.0,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._limit = limit
        self._window = window_seconds
        self._monotonic = monotonic
        self._seen: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    # Beyond this many remembered clients, the quiet ones are forgotten (and, if a crowd is still
    # too large, the longest quiet), so memory stays bounded whatever arrives.
    _MAX_CLIENTS = 1024

    def allow(self, client: str) -> bool:
        now = self._monotonic()
        with self._lock:
            if client not in self._seen and len(self._seen) >= self._MAX_CLIENTS:
                self._prune(now)
            history = self._seen.setdefault(client, deque())
            while history and now - history[0] >= self._window:
                history.popleft()
            if len(history) >= self._limit:
                return False
            history.append(now)
            return True

    def _prune(self, now: float) -> None:
        for key in [k for k, v in self._seen.items() if not v or now - v[-1] >= self._window]:
            del self._seen[key]
        if len(self._seen) >= self._MAX_CLIENTS:
            by_last_seen = sorted(self._seen, key=lambda key: self._seen[key][-1])
            for key in by_last_seen[: len(self._seen) - self._MAX_CLIENTS + 1]:
                del self._seen[key]

    @property
    def clients(self) -> int:
        with self._lock:
            return len(self._seen)

    def retry_after(self, client: str) -> int:
        now = self._monotonic()
        with self._lock:
            history = self._seen.get(client)
            if not history:
                return 1
            return max(1, int(self._window - (now - history[0])) + 1)
