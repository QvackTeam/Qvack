"""Consents (Т-§19.4, ТЗ Ф4 WP18.4): `consent.given {kind, version}`, `consent.revoked`.

Without `consent.given {kind: terms}` of the current `terms_version` sessions do not start
(`CONSENT_REQUIRED`). `research` gates the evaluation sets (filter of WP16.7).
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from redis.asyncio import Redis

from quack.config import Settings
from quack.db import Db

type ConsentKind = Literal["terms", "research"]


async def give_consent(
    db: Db,
    learner_id: UUID,
    *,
    kind: ConsentKind,
    version: str,
    redis: Redis | None = None,
) -> None:
    """`POST /v1/consents`: writes `consent.given`."""
    raise NotImplementedError


async def revoke_research(
    db: Db, learner_id: UUID, *, version: str, redis: Redis | None = None
) -> None:
    """`DELETE /v1/consents/research`: writes `consent.revoked {kind: research}`."""
    raise NotImplementedError


async def has_current_terms(db: Db, learner_id: UUID, settings: Settings) -> bool:
    """`consent.given {kind: terms, version: terms_version}` exists. With no `terms_version`
    configured (D-C-105) nobody has it."""
    raise NotImplementedError
