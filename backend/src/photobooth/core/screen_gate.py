"""ASGI gate for the TV screen listener: the booth screens on the LAN, never Admin.

The TV's browser reaches the kiosk app through this gate on its own LAN port. The gate:

- refuses Admin and launcher paths outright (404), whatever cookie the request carries;
- accepts only a Host typed as an IP address (anti DNS-rebinding, like the kiosk's allowlist);
- presents the request to the kiosk app as if it came to the kiosk address: the Host header
  becomes the kiosk's, and an Origin equal to the TV page's own origin (the browser's same-origin
  proof) becomes the kiosk origin. Any other Origin is passed on unchanged, so the kiosk app's
  exact Origin allowlist still refuses it.

Pairing, the device cookie and the device key are unchanged: the TV pairs with a short code an
organizer shows in Admin (modules.screen).
"""

from __future__ import annotations

import ipaddress

from starlette.types import ASGIApp, Receive, Scope, Send

from photobooth.core.host_guard import host_name

_BLOCKED_PREFIXES = ("/admin", "/api/admin", "/kiosk", "/api/openapi.json", "/docs", "/redoc")


def is_blocked_path(path: str) -> bool:
    lowered = path.lower()
    return any(
        lowered == prefix or lowered.startswith(prefix + "/") for prefix in _BLOCKED_PREFIXES
    )


def _is_ip_host(raw: bytes) -> bool:
    name = host_name(raw)
    if name is None:
        return False
    try:
        ipaddress.ip_address(name)
    except ValueError:
        return False
    return True


async def _refuse(scope: Scope, send: Send, status: int, body: bytes) -> None:
    if scope["type"] == "websocket":
        await send({"type": "websocket.close", "code": 1008})
        return
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


class ScreenGateMiddleware:
    def __init__(self, app: ASGIApp, kiosk_port: int) -> None:
        self._app = app
        self._kiosk_host = f"127.0.0.1:{kiosk_port}".encode("latin-1")
        self._kiosk_origin = b"http://" + self._kiosk_host

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self._app(scope, receive, send)
            return
        if is_blocked_path(str(scope.get("path", ""))):
            await _refuse(scope, send, 404, b"not found")
            return
        headers: list[tuple[bytes, bytes]] = list(scope.get("headers") or [])
        host = next((value for name, value in headers if name == b"host"), b"")
        if not _is_ip_host(host):
            await _refuse(scope, send, 400, b"invalid host header")
            return
        same_origin = b"http://" + host.lower()
        rewritten: list[tuple[bytes, bytes]] = []
        for name, value in headers:
            if name == b"host":
                rewritten.append((name, self._kiosk_host))
            elif name == b"origin" and value.lower() == same_origin:
                rewritten.append((name, self._kiosk_origin))
            else:
                rewritten.append((name, value))
        await self._app(dict(scope, headers=rewritten), receive, send)
