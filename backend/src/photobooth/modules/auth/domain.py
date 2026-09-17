"""Auth domain: admin user, sessions, password policy, login throttle and ports."""

from __future__ import annotations

import re
import threading
from abc import ABC, abstractmethod
from collections import deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

MIN_PASSWORD_LENGTH = 12
# Dummy dev profile only (user decision 2026-09-17): short local test passwords such as admin123.
DEV_MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 256
USERNAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_.-]{2,31}$")


class AuthError(Exception):
    """Base for authentication failures."""


class InvalidCredentialsError(AuthError):
    def __init__(self) -> None:
        super().__init__("invalid username or password")


class LoginThrottledError(AuthError):
    def __init__(self, retry_after_seconds: int) -> None:
        super().__init__("too many failed logins; try again later")
        self.retry_after_seconds = retry_after_seconds


class PasswordPolicyError(AuthError):
    """The new password does not meet the policy."""


def normalize_username(username: str) -> str:
    value = username.strip().lower()
    if not USERNAME_PATTERN.fullmatch(value):
        raise PasswordPolicyError(
            "username must be 3-32 characters: lowercase letters, digits, '.', '_' or '-'"
        )
    return value


def check_password_policy(
    password: str, username: str, min_length: int = MIN_PASSWORD_LENGTH
) -> None:
    if len(password) < min_length:
        raise PasswordPolicyError(f"password must be at least {min_length} characters")
    if len(password) > MAX_PASSWORD_LENGTH:
        raise PasswordPolicyError(f"password must be at most {MAX_PASSWORD_LENGTH} characters")
    if password.strip().lower() == username.lower():
        raise PasswordPolicyError("password must not equal the username")


@dataclass(frozen=True)
class AdminUser:
    id: str
    username: str
    password_hash: str
    created_at: datetime
    updated_at: datetime
    last_login_at: datetime | None


@dataclass
class AdminSession:
    """Session token and device credential are stored as hashes; the CSRF token is kept only in
    process memory. A session is bound to the paired device that logged in."""

    token_hash: str
    csrf_token: str
    user_id: str
    username: str
    device_hash: str
    created_at: float
    last_seen_at: float
    expires_at: float


class AdminUserRepository(ABC):
    @abstractmethod
    def get_by_username(self, username: str) -> AdminUser | None: ...

    @abstractmethod
    def upsert_password(self, user: AdminUser) -> AdminUser:
        """Create the user or replace its password hash."""

    @abstractmethod
    def record_login(self, user_id: str, at: datetime, password_hash: str | None) -> None:
        """Set last_login_at; replace the hash when it was upgraded (rehash)."""


class PasswordHasher(Protocol):
    def hash(self, password: str) -> str: ...

    def verify(self, password_hash: str, password: str) -> bool: ...

    def needs_rehash(self, password_hash: str) -> bool: ...


class AdminSessionStore(Protocol):
    def save(self, session: AdminSession) -> None: ...

    def get(self, token_hash: str) -> AdminSession | None: ...

    def delete(self, token_hash: str) -> None: ...

    def delete_user(self, user_id: str) -> None: ...


class LoginThrottle:
    """Per-key failure window: `max_failures` within `window_s` locks the key for `lockout_s`.

    Thread-safe. `admit` reserves an attempt atomically: attempts still being verified count as
    potential failures, so a concurrent burst can never exceed `max_failures` verifications per key.
    Every admitted attempt must be settled exactly once.
    """

    def __init__(
        self,
        clock: Callable[[], float],
        max_failures: int = 5,
        window_s: float = 900,
        lockout_s: float = 300,
    ) -> None:
        self._clock = clock
        self._max = max_failures
        self._window = window_s
        self._lockout = lockout_s
        self._failures: dict[str, deque[float]] = {}
        self._locked_until: dict[str, float] = {}
        self._pending: dict[str, int] = {}
        self._lock = threading.Lock()

    def admit(self, keys: Sequence[str]) -> None:
        with self._lock:
            now = self._clock()
            for key in keys:
                until = self._locked_until.get(key)
                if until is not None and now < until:
                    raise LoginThrottledError(int(until - now) + 1)
                if until is not None:
                    del self._locked_until[key]
                failures = self._prune(key, now)
                if failures + self._pending.get(key, 0) >= self._max:
                    raise LoginThrottledError(1)
            for key in keys:
                self._pending[key] = self._pending.get(key, 0) + 1

    def settle(
        self, keys: Sequence[str], failed: bool, clear_on_success: Sequence[str] = ()
    ) -> None:
        with self._lock:
            now = self._clock()
            for key in keys:
                remaining = self._pending.get(key, 0) - 1
                if remaining > 0:
                    self._pending[key] = remaining
                else:
                    self._pending.pop(key, None)
                if failed:
                    failures = self._failures.setdefault(key, deque())
                    failures.append(now)
                    self._prune(key, now)
                    if len(failures) >= self._max:
                        self._locked_until[key] = now + self._lockout
                        failures.clear()
            if not failed:
                for key in clear_on_success:
                    self._failures.pop(key, None)

    def _prune(self, key: str, now: float) -> int:
        failures = self._failures.get(key)
        if failures is None:
            return 0
        while failures and now - failures[0] > self._window:
            failures.popleft()
        if not failures:
            del self._failures[key]
            return 0
        return len(failures)
