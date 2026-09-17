"""Admin file uploads: bounded admission and a multipart reader that runs after authentication.

Routes must not declare `Form`/`UploadFile` parameters: FastAPI would parse (and spool) the body
before the device/admin dependencies run. These helpers read the body only when called, keep it in
memory under a hard cap, and never trust the client's file name.
"""

from __future__ import annotations

import threading
from collections.abc import AsyncGenerator

from fastapi import HTTPException, Request, status
from starlette.datastructures import UploadFile
from starlette.formparsers import MultiPartException, MultiPartParser

MAX_FIELD_BYTES = 256


class UploadAdmission:
    """Bounds concurrent uploads (each holds at most one body in memory)."""

    def __init__(self, limit: int) -> None:
        self._slots = threading.BoundedSemaphore(limit)

    def try_acquire(self) -> bool:
        return self._slots.acquire(blocking=False)

    def release(self) -> None:
        self._slots.release()

    def busy(self) -> HTTPException:
        return HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="another upload is in progress; try again",
            headers={"Retry-After": "2"},
        )


def _parser(request: Request, max_bytes: int, fields: int) -> MultiPartParser:
    class InMemoryParser(MultiPartParser):
        # The body is capped below this size, so file parts never roll over to a temp file.
        spool_max_size = max_bytes + 1

    return InMemoryParser(
        request.headers,
        _capped_stream(request, max_bytes),
        max_files=1,
        max_fields=fields,
        max_part_size=MAX_FIELD_BYTES,
    )


async def _capped_stream(request: Request, max_bytes: int) -> AsyncGenerator[bytes]:
    received = 0
    async for chunk in request.stream():
        received += len(chunk)
        if received > max_bytes:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE, detail="upload is too large"
            )
        yield chunk


async def read_upload(
    request: Request, max_bytes: int, fields: tuple[str, ...], file_field: str = "file"
) -> tuple[dict[str, str], bytes]:
    """Parse one multipart body: the named text fields plus the bytes of `file_field`."""
    if not request.headers.get("content-type", "").startswith("multipart/form-data"):
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail="use multipart/form-data"
        )
    parser = _parser(request, max_bytes, len(fields))
    try:
        form = await parser.parse()
    except MultiPartException as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="invalid multipart body"
        ) from exc
    try:
        values: dict[str, str] = {}
        for name in fields:
            value = form.get(name)
            if not isinstance(value, str):
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail=f"the '{name}' field is required",
                )
            values[name] = value
        upload = form.get(file_field)
        if not isinstance(upload, UploadFile):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"attach the file as the '{file_field}' part",
            )
        data = await upload.read(max_bytes + 1)
        if len(data) > max_bytes:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE, detail="upload is too large"
            )
        return values, data
    finally:
        await form.close()


def multipart_openapi(fields: dict[str, object], file_field: str = "file") -> dict[str, object]:
    """OpenAPI request body for routes that parse multipart themselves."""
    properties = {**fields, file_field: {"type": "string", "format": "binary"}}
    return {
        "requestBody": {
            "required": True,
            "content": {
                "multipart/form-data": {
                    "schema": {
                        "type": "object",
                        "required": [*fields, file_field],
                        "properties": properties,
                    }
                }
            },
        }
    }
