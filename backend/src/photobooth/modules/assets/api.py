"""Logo/background asset routes under /api/admin/assets (paired device + admin session).

Frames are not uploaded here (Phase 5). The client file name and any path it sends are ignored;
content is stored under a content-addressed key chosen by the server.
"""

from __future__ import annotations

import threading
from collections.abc import AsyncGenerator
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Path, Request, Response, status
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile as StarletteUploadFile
from starlette.formparsers import MultiPartException, MultiPartParser

from photobooth.core.admin_gate import require_admin
from photobooth.core.web import provide, require_device
from photobooth.modules.assets.domain import (
    LIMITS,
    AssetKind,
    AssetNotFoundError,
    AssetValidationError,
)
from photobooth.modules.assets.schemas import MediaAssetResponse
from photobooth.modules.assets.service import AssetService

router = APIRouter(
    prefix="/api/admin/assets",
    tags=["admin-assets"],
    dependencies=[Depends(require_device), Depends(require_admin)],
)

Service = Annotated[AssetService, Depends(provide(AssetService))]
AssetId = Annotated[
    str, Path(pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
]
# Largest accepted image plus generous room for multipart framing and the `kind` field.
MAX_UPLOAD_BODY = max(limit.max_bytes for limit in LIMITS.values()) + 64 * 1024
UPLOAD_OPENAPI: dict[str, Any] = {
    "requestBody": {
        "required": True,
        "content": {
            "multipart/form-data": {
                "schema": {
                    "type": "object",
                    "required": ["kind", "file"],
                    "properties": {
                        "kind": {"type": "string", "enum": [k.value for k in AssetKind]},
                        "file": {"type": "string", "format": "binary"},
                    },
                }
            }
        },
    }
}


class UploadAdmission:
    """Bounds concurrent uploads (each holds at most MAX_UPLOAD_BODY bytes in memory)."""

    def __init__(self, limit: int) -> None:
        self._slots = threading.BoundedSemaphore(limit)

    def try_acquire(self) -> bool:
        return self._slots.acquire(blocking=False)

    def release(self) -> None:
        self._slots.release()


Admission = Annotated[UploadAdmission, Depends(provide(UploadAdmission))]


class _InMemoryMultiPartParser(MultiPartParser):
    # The body is already capped below this size, so file parts never roll over to a temp file.
    spool_max_size = MAX_UPLOAD_BODY + 1


async def _capped_stream(request: Request) -> AsyncGenerator[bytes]:
    received = 0
    async for chunk in request.stream():
        received += len(chunk)
        if received > MAX_UPLOAD_BODY:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE, detail="upload is too large"
            )
        yield chunk


async def _read_form(request: Request) -> tuple[AssetKind, bytes]:
    """Parse the multipart body only after the device and admin gates passed (no Form params,
    so FastAPI does not parse before the dependencies run)."""
    if not request.headers.get("content-type", "").startswith("multipart/form-data"):
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail="use multipart/form-data"
        )
    parser = _InMemoryMultiPartParser(
        request.headers, _capped_stream(request), max_files=1, max_fields=1, max_part_size=64
    )
    try:
        form = await parser.parse()
    except MultiPartException as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="invalid multipart body"
        ) from exc
    try:
        kind_value, upload = form.get("kind"), form.get("file")
        if not isinstance(kind_value, str):
            raise AssetValidationError("Asset kind must be 'logo' or 'background'.")
        try:
            kind = AssetKind(kind_value)
        except ValueError as exc:
            raise AssetValidationError("Asset kind must be 'logo' or 'background'.") from exc
        if not isinstance(upload, StarletteUploadFile):
            raise AssetValidationError("Attach the image as the `file` part.")
        data = await upload.read(LIMITS[kind].max_bytes + 1)
        if len(data) > LIMITS[kind].max_bytes:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail=f"file is larger than {LIMITS[kind].max_bytes // (1024 * 1024)} MB",
            )
        return kind, data
    except AssetValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc
    finally:
        await form.close()


@router.post(
    "",
    response_model=MediaAssetResponse,
    status_code=status.HTTP_201_CREATED,
    openapi_extra=UPLOAD_OPENAPI,
)
async def upload_asset(
    request: Request, service: Service, admission: Admission
) -> MediaAssetResponse:
    if not admission.try_acquire():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="another upload is in progress; try again",
            headers={"Retry-After": "2"},
        )
    try:
        kind, data = await _read_form(request)
        # Decoding, hashing, fsync and database writes run off the event loop the two
        # listeners share.
        asset = await run_in_threadpool(service.upload, kind.value, data)
        return MediaAssetResponse.of(asset)
    except AssetValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc
    finally:
        admission.release()


@router.get("/{asset_id}", response_model=MediaAssetResponse)
def asset_metadata(asset_id: AssetId, service: Service) -> MediaAssetResponse:
    try:
        return MediaAssetResponse.of(service.get(asset_id))
    except AssetNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get(
    "/{asset_id}/content",
    response_class=Response,
    responses={200: {"content": {"image/png": {}, "image/jpeg": {}}}},
)
def asset_content(asset_id: AssetId, service: Service) -> Response:
    try:
        asset, data = service.content(asset_id)
    except AssetNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return Response(
        content=data,
        media_type=asset.mime,
        headers={
            "Content-Disposition": "inline",
            "Cache-Control": "private, no-cache",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'; sandbox",
            "ETag": f'"{asset.sha256}"',
        },
    )
