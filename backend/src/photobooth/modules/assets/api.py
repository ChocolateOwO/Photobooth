from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Request, Response, status
from starlette.concurrency import run_in_threadpool

from photobooth.core.admin_gate import require_admin
from photobooth.core.uploads import UploadAdmission, multipart_openapi, read_upload
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

# Frames are uploaded through /api/admin/frames, which validates them against a template first.
UPLOADABLE_KINDS = (AssetKind.LOGO, AssetKind.BACKGROUND)

Service = Annotated[AssetService, Depends(provide(AssetService))]
Admission = Annotated[UploadAdmission, Depends(provide(UploadAdmission))]
AssetId = Annotated[
    str, Path(pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
]
# Largest accepted image plus generous room for multipart framing and the `kind` field.
MAX_UPLOAD_BODY = max(limit.max_bytes for limit in LIMITS.values()) + 64 * 1024
UPLOAD_OPENAPI = multipart_openapi(
    {"kind": {"type": "string", "enum": [k.value for k in UPLOADABLE_KINDS]}}
)


async def _read_form(request: Request) -> tuple[AssetKind, bytes]:
    """Read the body only after the device and admin gates passed."""
    values, data = await read_upload(request, MAX_UPLOAD_BODY, ("kind",))
    try:
        kind = AssetKind(values["kind"])
        if kind not in UPLOADABLE_KINDS:
            raise ValueError(kind)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Asset kind must be 'logo' or 'background'.",
        ) from exc
    if len(data) > LIMITS[kind].max_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=f"file is larger than {LIMITS[kind].max_bytes // (1024 * 1024)} MB",
        )
    return kind, data


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
        raise admission.busy()
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
