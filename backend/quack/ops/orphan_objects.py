"""`ops orphan-objects --since <t> [--dry-run]` (Д-§8.3 step 8, ТЗ Ф4 WP9.6, D-C-211).

After Postgres is restored from a dump, `quack-learners` may hold files that the restored log
does not know: uploads whose events were lost. They belong to no record, and account deletion by
the journal does not cover them, so they are deleted. Only objects newer than `since` (the time
of the dump) are looked at; an object is kept when Postgres refers to it:

- a canvas chunk (`learners/{learner}/canvas/{session}/{canvas}/...`) when the canvas has a row
  in `content.canvas_boards` (chunks are found by prefix, no row names them);
- any other key when it is the key of a material, a material page or an export, or when it
  stands in an event of the same learner (`photo.uploaded`, `agent.completed.result_ref`, ...)
  or in an artifact version of the learner.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from quack.db import Db
from quack.storage.objects import ObjectInfo, ObjectStore

_KEYS_IN_TABLES = (
    "SELECT 1 AS found FROM content.materials "
    "WHERE learner_id = %(learner_id)s AND object_key = %(key)s "
    "UNION ALL SELECT 1 FROM content.material_pages "
    "WHERE learner_id = %(learner_id)s AND image_key = %(key)s "
    "UNION ALL SELECT 1 FROM content.exports "
    "WHERE learner_id = %(learner_id)s AND object_key = %(key)s "
    "LIMIT 1"
)
_KEY_IN_EVENTS = (
    "SELECT 1 AS found FROM core.events "
    "WHERE learner_id = %(learner_id)s AND strpos(payload::text, %(key)s) > 0 LIMIT 1"
)
_KEY_IN_ARTIFACTS = (
    "SELECT 1 AS found FROM content.artifact_versions "
    "WHERE learner_id = %(learner_id)s AND strpos(content::text, %(key)s) > 0 LIMIT 1"
)
_CANVAS = (
    "SELECT 1 AS found FROM content.canvas_boards "
    "WHERE learner_id = %(learner_id)s AND canvas_id = %(canvas_id)s"
)

_PREFIX = "learners/"
_CANVAS_PARTS = 6  # learners / {learner} / canvas / {session} / {canvas} / {file}


@dataclass(frozen=True)
class OrphanReport:
    checked: int
    orphans: list[str]
    deleted: int


def _uuid(text: str) -> UUID | None:
    try:
        return UUID(text)
    except ValueError:
        return None


async def _referenced(db: Db, learner_id: UUID, key: str, canvas_id: UUID | None) -> bool:
    if canvas_id is not None:
        return (
            await db.fetch_one(_CANVAS, {"learner_id": learner_id, "canvas_id": canvas_id})
            is not None
        )
    params = {"learner_id": learner_id, "key": key}
    for query in (_KEYS_IN_TABLES, _KEY_IN_EVENTS, _KEY_IN_ARTIFACTS):
        if await db.fetch_one(query, params) is not None:
            return True
    return False


async def _kept(db: Db, info: ObjectInfo) -> bool:
    parts = info.key.split("/")
    learner_id = _uuid(parts[1]) if len(parts) > 1 else None
    if learner_id is None:
        return False  # not under a learner: nothing in Postgres can refer to it
    canvas_id = None
    if len(parts) >= _CANVAS_PARTS and parts[2] == "canvas":
        canvas_id = _uuid(parts[4])
        if canvas_id is None:
            return False
    return await _referenced(db, learner_id, info.key, canvas_id)


async def orphan_objects(
    db: Db, store: ObjectStore, since: datetime, *, dry_run: bool = False
) -> OrphanReport:
    """Objects of `quack-learners` newer than `since` without a reference in Postgres; they are
    deleted unless `dry_run`. Sorted by key."""
    newer = [o for o in await store.list_objects(_PREFIX) if o.last_modified > since]
    orphans = sorted([o.key for o in newer if not await _kept(db, o)])
    if orphans and not dry_run:
        await store.delete_keys(orphans)
    return OrphanReport(checked=len(newer), orphans=orphans, deleted=0 if dry_run else len(orphans))
