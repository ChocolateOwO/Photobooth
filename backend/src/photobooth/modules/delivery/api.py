"""Guest routes, mounted ONLY on the LAN delivery listener.

- GET /d/{token}                          the landing page (the QR code opens this)
- GET /d/{token}/files/{output_id}        one finished photo (?download=1 saves it)
- GET /d/{token}/all.zip                  every photo of the visit, streamed as a ZIP

Every failure (unknown, expired or revoked link; a photo of another visit; a missing file)
answers exactly like a path that does not exist.
"""

from __future__ import annotations

import zipfile
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Request, status
from fastapi.responses import HTMLResponse, Response, StreamingResponse

from photobooth.core.web import provide
from photobooth.modules.delivery.domain import DeliveryNotFoundError
from photobooth.modules.delivery.landing import (
    CONTENT_SECURITY_POLICY,
    download_name,
    render_page,
)
from photobooth.modules.delivery.service import DeliveryService, RequestBudget

router = APIRouter(prefix="/d", include_in_schema=False)


@dataclass(frozen=True)
class DeliveryBudgets:
    """Per-client limits: every request, and the heavier Download All."""

    requests: RequestBudget
    archives: RequestBudget


Service = Annotated[DeliveryService, Depends(provide(DeliveryService))]
Budgets = Annotated[DeliveryBudgets, Depends(provide(DeliveryBudgets))]
Token = Annotated[str, Path(min_length=1, max_length=128)]
OutputId = Annotated[
    str, Path(pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
]


def _not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND)


def _client(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _admit(budget: RequestBudget, request: Request) -> None:
    client = _client(request)
    if not budget.allow(client):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="too many requests",
            headers={"Retry-After": str(budget.retry_after(client))},
        )


@router.get("/{token}", response_class=HTMLResponse)
def landing(token: Token, request: Request, service: Service, budgets: Budgets) -> HTMLResponse:
    _admit(budgets.requests, request)
    try:
        opened = service.open(token)
    except DeliveryNotFoundError as exc:
        raise _not_found() from exc
    return HTMLResponse(
        render_page(token, opened.files, opened.token.expires_at),
        headers={"Content-Security-Policy": CONTENT_SECURITY_POLICY},
    )


@router.get("/{token}/files/{output_id}")
def one_file(
    token: Token,
    output_id: OutputId,
    request: Request,
    service: Service,
    budgets: Budgets,
    download: bool = False,
) -> Response:
    _admit(budgets.requests, request)
    try:
        opened = service.open(token)
        _file, data = service.file(token, output_id)
    except DeliveryNotFoundError as exc:
        raise _not_found() from exc
    position = next(
        (n for n, candidate in enumerate(opened.files, 1) if candidate.output_id == output_id), 1
    )
    name = download_name(position, len(opened.files))
    if download:
        service.count_download(opened.token)
    return Response(
        content=data,
        media_type="image/jpeg",
        headers={
            "Content-Disposition": f'{"attachment" if download else "inline"}; filename="{name}"',
            "Content-Length": str(len(data)),
            "Content-Security-Policy": "default-src 'none'; sandbox",
        },
    )


class _Chunks:
    """A write-only sink: zipfile writes into it and the response takes what was written."""

    def __init__(self) -> None:
        self._parts: list[bytes] = []

    def write(self, data: bytes) -> int:
        self._parts.append(bytes(data))
        return len(data)

    def flush(self) -> None:
        return None

    def close(self) -> None:
        return None

    def take(self) -> bytes:
        taken = b"".join(self._parts)
        self._parts.clear()
        return taken


@router.get("/{token}/all.zip")
def download_all(
    token: Token, request: Request, service: Service, budgets: Budgets
) -> StreamingResponse:
    _admit(budgets.requests, request)
    _admit(budgets.archives, request)
    try:
        link, files = service.everything(token)
        # Every photo is read before the first byte is sent, so a missing file is still an
        # honest "not found" rather than a truncated archive.
        contents = [(file, service.read(link, file.output_id)) for file in files]
    except DeliveryNotFoundError as exc:
        raise _not_found() from exc
    except Exception as exc:
        raise _not_found() from exc
    service.count_download(link)

    def stream() -> Iterator[bytes]:
        sink = _Chunks()
        # JPEGs do not compress further; storing them keeps the booth fast.
        with zipfile.ZipFile(sink, mode="w", compression=zipfile.ZIP_STORED) as archive:
            for position, (file, data) in enumerate(contents, start=1):
                stamp = file.rendered_at.astimezone()
                info = zipfile.ZipInfo(
                    download_name(position, len(contents)),
                    date_time=(
                        stamp.year,
                        stamp.month,
                        stamp.day,
                        stamp.hour,
                        stamp.minute,
                        stamp.second,
                    ),
                )
                info.compress_type = zipfile.ZIP_STORED
                archive.writestr(info, data)
                yield sink.take()
        yield sink.take()

    return StreamingResponse(
        stream(),
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="photobooth-photos.zip"'},
    )
