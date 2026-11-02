"""Upload and read of materials (ТЗ Ф4 WP20.1; Т-§2.3, Т-§3.1, Т-§19.8).

The file goes to the object store first, then the `content.materials` row and
`material.uploaded` in one transaction (Т-§2.3); the dispatcher queues `material.parse` (S6,
stream A). The domain must be the learner's: its `domain.created` is in the event log (law 1;
`quack.graph.read` is not there yet, D-C-113).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from redis.asyncio import Redis

from quack.config import Settings
from quack.db import Db
from quack.storage.objects import ObjectStore


class MaterialNotFound(Exception):
    """No such material (or domain) of this learner: 404."""


@dataclass(frozen=True)
class MaterialPage:
    page: int
    text: str
    image_url: str | None


@dataclass(frozen=True)
class Material:
    material_id: UUID
    domain_id: UUID | None
    session_id: UUID | None
    mime: str
    status: str
    pages_count: int | None
    created_at: datetime


@dataclass(frozen=True)
class MaterialDetail:
    material: Material
    file_url: str
    pages: list[MaterialPage]


async def upload_material(
    db: Db,
    storage: ObjectStore,
    settings: Settings,
    *,
    learner_id: UUID,
    domain_id: UUID,
    data: bytes,
    session_id: UUID | None = None,
    redis: Redis | None = None,
) -> Material:
    """Store a PDF or an image (type by content, `upload_max_mb`) and record it.
    `UploadRejected`, `MaterialNotFound` (unknown domain), `StorageUnavailable`."""
    raise NotImplementedError


async def list_materials(db: Db, *, learner_id: UUID, domain_id: UUID) -> list[Material]:
    """`GET /v1/domains/{id}/materials`, newest first."""
    raise NotImplementedError


async def get_material(
    db: Db, storage: ObjectStore, settings: Settings, *, learner_id: UUID, material_id: UUID
) -> MaterialDetail:
    """`GET /v1/materials/{id}`: pages with their text and signed links (`object_url_ttl_s`)."""
    raise NotImplementedError
