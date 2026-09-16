"""ASGI middleware for the kiosk listener: Host allowlist (anti DNS-rebinding) and body cap."""

from __future__ import annotations

from collections.abc import Iterable

from starlette.types import ASGIApp, Message, Receive, Scope, Send


def _host_name(raw: bytes | None) -> str | None:
    if not raw:
        return None
    value = raw.decode("latin-1").strip().lower()
    if value.startswith("["):  # IPv6 literal: [::1]:8111
        end = value.find("]")
        return value[1:end] if end > 0 else None
    return value.rsplit(":", 1)[0] if ":" in value else value


async def _plain_response(send: Send, status: int, body: bytes) -> None:
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"text/plain; charset=utf-8"),
                (b"content-length", str(len(body)).encode("ascii")),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


class HostAllowlistMiddleware:
    """Rejects requests whose Host header is not an allowlisted name (port ignored)."""

    def __init__(self, app: ASGIApp, allowed_hosts: Iterable[str]) -> None:
        self._app = app
        self._allowed = frozenset(h.lower() for h in allowed_hosts)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self._app(scope, receive, send)
            return
        raw = dict(scope.get("headers") or []).get(b"host")
        if _host_name(raw) not in self._allowed:
            if scope["type"] == "websocket":
                await send({"type": "websocket.close", "code": 1008})
                return
            await _plain_response(send, 400, b"invalid host header")
            return
        await self._app(scope, receive, send)


class BodySizeLimitMiddleware:
    """Caps request bodies (declared length and streamed bytes)."""

    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self._app = app
        self._max = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return
        declared = dict(scope.get("headers") or []).get(b"content-length")
        if declared is not None:
            try:
                too_big = int(declared) > self._max
            except ValueError:
                await _plain_response(send, 400, b"invalid content-length")
                return
            if too_big:
                await _plain_response(send, 413, b"request body too large")
                return

        received = 0
        response_started = False

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self._max:
                    raise _BodyTooLargeError
            return message

        async def tracking_send(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self._app(scope, limited_receive, tracking_send)
        except _BodyTooLargeError:
            if not response_started:
                await _plain_response(send, 413, b"request body too large")


class _BodyTooLargeError(Exception):
    pass
