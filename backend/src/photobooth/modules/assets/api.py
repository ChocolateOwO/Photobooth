"""Logo/background asset routes under /api/admin/assets (paired device + admin session).

Frames are not uploaded here (Phase 5). The client file name and any path it sends are ignored;
content is stored under a content-addressed key chosen by the server.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Path,
    Response,
    UploadFile,
    status,
)

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
READ_CHUNK = 1024 * 1024


async def _read_capped(upload: UploadFile, max_bytes: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while chunk := await upload.read(READ_CHUNK):
        total += len(chunk)
        if total > max_bytes:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail=f"file is larger than {max_bytes // (1024 * 1024)} MB",
            )
        chunks.append(chunk)
    return b"".join(chunks)


@router.post("", response_model=MediaAssetResponse, status_code=status.HTTP_201_CREATED)
async def upload_asset(
    service: Service,
    kind: Annotated[AssetKind, Form()],
    file: Annotated[UploadFile, File()],
) -> MediaAssetResponse:
    data = await _read_capped(file, LIMITS[kind].max_bytes)
    try:
        return MediaAssetResponse.of(service.upload(kind.value, data))
    except AssetValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc


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
