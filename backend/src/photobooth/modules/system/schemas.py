"""Public API contracts for the system module."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: Literal["ok", "error"]
    instance: str
    database: Literal["ok", "error"]


class VersionResponse(BaseModel):
    app_version: str
    api_version: int
    instance: str
    schema_revision: str | None
    git_commit: str | None
