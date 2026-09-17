"""In-process admin session store. Sessions never survive a restart (like device credentials)."""

from __future__ import annotations

import threading

from photobooth.modules.auth.domain import AdminSession


class InMemoryAdminSessionStore:
    def __init__(self, max_sessions: int = 64) -> None:
        self._sessions: dict[str, AdminSession] = {}
        self._lock = threading.Lock()
        self._max = max_sessions

    def save(self, session: AdminSession) -> None:
        with self._lock:
            if len(self._sessions) >= self._max and session.token_hash not in self._sessions:
                oldest = min(self._sessions.values(), key=lambda s: s.last_seen_at)
                del self._sessions[oldest.token_hash]
            self._sessions[session.token_hash] = session

    def get(self, token_hash: str) -> AdminSession | None:
        with self._lock:
            return self._sessions.get(token_hash)

    def delete(self, token_hash: str) -> None:
        with self._lock:
            self._sessions.pop(token_hash, None)

    def delete_user(self, user_id: str) -> None:
        with self._lock:
            for key in [k for k, s in self._sessions.items() if s.user_id == user_id]:
                del self._sessions[key]
