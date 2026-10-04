"""Two uvicorn servers (kiosk + delivery) in one process and one event loop (workers=1)."""

from __future__ import annotations

import asyncio
import ipaddress
from dataclasses import dataclass

import uvicorn
from starlette.types import ASGIApp

from photobooth.core.config import AppSettings
from photobooth.core.errors import InstanceGuardError


@dataclass(frozen=True)
class ListenerSpec:
    name: str
    host: str
    port: int


def listener_specs(settings: AppSettings) -> tuple[ListenerSpec, ListenerSpec]:
    kiosk = ListenerSpec("kiosk", settings.kiosk_host, settings.kiosk_port)
    if not ipaddress.ip_address(kiosk.host).is_loopback:
        raise InstanceGuardError("bind", f"kiosk listener must be loopback, got {kiosk.host}")
    delivery = ListenerSpec("delivery", settings.delivery_host, settings.delivery_port)
    return kiosk, delivery


def screen_spec(settings: AppSettings) -> ListenerSpec | None:
    """The optional TV screen listener (booth screens only, see core.screen_gate)."""
    if settings.screen_port is None:
        return None
    return ListenerSpec("screen", settings.screen_host, settings.screen_port)


def build_server(app: ASGIApp, spec: ListenerSpec) -> uvicorn.Server:
    config = uvicorn.Config(
        app,
        host=spec.host,
        port=spec.port,
        workers=1,
        access_log=False,
        log_config=None,
        server_header=False,
        proxy_headers=False,
        lifespan="off",
    )
    return uvicorn.Server(config)


async def serve_together(servers: list[uvicorn.Server]) -> None:
    """Run all servers; when any one stops (error or signal), stop the others."""
    tasks = [asyncio.create_task(server.serve()) for server in servers]
    try:
        done, _pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for server in servers:
            server.should_exit = True
        results = await asyncio.gather(*tasks, return_exceptions=True)
    for server, result in zip(servers, results, strict=True):
        if isinstance(result, BaseException):
            raise result
        if not server.started:
            raise RuntimeError(f"listener failed to start on port {server.config.port}")
    del done
