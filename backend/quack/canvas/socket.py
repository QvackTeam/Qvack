"""The WebSocket of a canvas (ТЗ Ф4 WP21.2). Red stub: tests first."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from redis.asyncio import Redis


async def publish_canvas(redis: Redis, canvas_id: UUID, message: dict[str, Any]) -> None:
    raise NotImplementedError
