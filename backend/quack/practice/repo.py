"""Reads of `core.events` by stream B (ТЗ Ф4 WP1.2: SQL lives in the package modules; A's
answer to D-B-122): parameters only `%(name)s`, every query filtered by `learner_id`."""

from __future__ import annotations

from uuid import UUID

from quack.db.db import Db
from quack.events.log import StoredEvent

_COLUMNS = (
    "learner_id, seq, id, type, schema_version, actor, domain_id, session_id, causation_seq, "
    "correlation_id, idempotency_key, payload_hash, occurred_at, payload, source_refs"
)
_BY_KEY = (
    f"SELECT {_COLUMNS} FROM core.events "
    "WHERE learner_id = %(learner_id)s AND idempotency_key = %(key)s"
)
_BY_SEQ = f"SELECT {_COLUMNS} FROM core.events WHERE learner_id = %(learner_id)s AND seq = %(seq)s"


async def event_by_key(db: Db, *, learner_id: UUID, key: str) -> StoredEvent | None:
    return await db.fetch_one(_BY_KEY, {"learner_id": learner_id, "key": key}, row=StoredEvent)


async def event_by_seq(db: Db, *, learner_id: UUID, seq: int) -> StoredEvent | None:
    return await db.fetch_one(_BY_SEQ, {"learner_id": learner_id, "seq": seq}, row=StoredEvent)
