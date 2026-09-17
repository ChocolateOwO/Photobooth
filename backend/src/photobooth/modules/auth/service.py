"""Admin authentication use cases."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from photobooth.modules.auth.domain import (
    AdminSession,
    AdminSessionStore,
    AdminUser,
    AdminUserRepository,
    InvalidCredentialsError,
    LoginThrottle,
    LoginThrottledError,
    PasswordHasher,
    check_password_policy,
    normalize_username,
)

VERIFY_WAIT_SECONDS = 10
SESSION_IDLE_SECONDS = 30 * 60
SESSION_ABSOLUTE_SECONDS = 8 * 60 * 60
GLOBAL_THROTTLE_KEY = "*"


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class LoginResult:
    session_token: str
    csrf_token: str
    username: str
    expires_at: float


@dataclass(frozen=True)
class SessionInfo:
    user_id: str
    username: str
    csrf_token: str
    expires_at: float
    idle_expires_at: float


class AuthService:
    """Session token is stored hashed; the CSRF token lives only in process memory and is given
    to the same-origin UI (mutations additionally need the device key)."""

    def __init__(
        self,
        users: AdminUserRepository,
        hasher: PasswordHasher,
        sessions: AdminSessionStore,
        throttle: LoginThrottle,
        monotonic: Callable[[], float] = time.monotonic,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._users = users
        self._hasher = hasher
        self._sessions = sessions
        self._throttle = throttle
        self._monotonic = monotonic
        self._now = now
        self._dummy_hash = hasher.hash(secrets.token_urlsafe(24))
        self._verify_slot = threading.BoundedSemaphore(1)

    def set_password(self, username: str, password: str) -> AdminUser:
        name = normalize_username(username)
        check_password_policy(password, name)
        now = self._now()
        user = self._users.upsert_password(
            AdminUser(
                id=str(uuid.uuid4()),
                username=name,
                password_hash=self._hasher.hash(password),
                created_at=now,
                updated_at=now,
                last_login_at=None,
            )
        )
        self._sessions.delete_user(user.id)  # a password change ends every existing session
        return user

    def login(self, username: str, password: str, device_token: str) -> LoginResult:
        name = username.strip().lower()[:64]
        keys = (GLOBAL_THROTTLE_KEY, name)
        self._throttle.admit(keys)  # reserves the attempt; settled exactly once below
        failed = True
        try:
            # One memory-hard verification at a time; a caller that can not get the slot soon is
            # told to retry instead of piling up worker threads.
            if not self._verify_slot.acquire(timeout=VERIFY_WAIT_SECONDS):
                failed = False  # not a password failure
                raise LoginThrottledError(1)
            try:
                user = self._users.get_by_username(name)
                # Always run one Argon2 verification so timing does not reveal unknown usernames.
                valid = self._hasher.verify(
                    user.password_hash if user else self._dummy_hash, password
                )
                if user is None or not valid:
                    raise InvalidCredentialsError()
                failed = False
                upgraded = (
                    self._hasher.hash(password)
                    if self._hasher.needs_rehash(user.password_hash)
                    else None
                )
            finally:
                self._verify_slot.release()
        finally:
            self._throttle.settle(keys, failed, clear_on_success=(name,))
        self._users.record_login(user.id, self._now(), upgraded)

        session_token = secrets.token_urlsafe(32)
        csrf_token = secrets.token_urlsafe(32)
        now = self._monotonic()
        self._sessions.save(
            AdminSession(
                token_hash=_digest(session_token),
                csrf_token=csrf_token,
                user_id=user.id,
                username=user.username,
                device_hash=_digest(device_token),
                created_at=now,
                last_seen_at=now,
                expires_at=now + SESSION_ABSOLUTE_SECONDS,
            )
        )
        return LoginResult(session_token, csrf_token, user.username, now + SESSION_ABSOLUTE_SECONDS)

    def session(self, session_token: str | None, device_token: str | None) -> SessionInfo | None:
        if not session_token or not device_token:
            return None
        token_hash = _digest(session_token)
        stored = self._sessions.get(token_hash)
        if stored is None:
            return None
        now = self._monotonic()
        if now >= stored.expires_at or now - stored.last_seen_at >= SESSION_IDLE_SECONDS:
            self._sessions.delete(token_hash)
            return None
        if not hmac.compare_digest(stored.device_hash, _digest(device_token)):
            return None
        stored.last_seen_at = now
        return SessionInfo(
            user_id=stored.user_id,
            username=stored.username,
            csrf_token=stored.csrf_token,
            expires_at=stored.expires_at,
            idle_expires_at=now + SESSION_IDLE_SECONDS,
        )

    def verify_csrf(self, session_token: str | None, csrf_token: str | None) -> bool:
        if not session_token or not csrf_token:
            return False
        stored = self._sessions.get(_digest(session_token))
        return stored is not None and hmac.compare_digest(stored.csrf_token, csrf_token)

    def logout(self, session_token: str | None) -> None:
        if session_token:
            self._sessions.delete(_digest(session_token))
