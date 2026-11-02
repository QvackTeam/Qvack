"""Canvases of a session (ТЗ Ф4 WP21.1; Т-§15.1, П-2.6, П-9.3).

A canvas belongs to a session (`session.started` of the learner in the log, law 1). Opened by a
task, the board gets a task block; a task made on the fly (`source = teacher`) without a
solution space also writes `agent.requested {kind: solution_space, task_id}` in the same
transaction as the row (WP12.4). The domain of a canvas is the domain of its session.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from psycopg.types.json import Jsonb
from redis.asyncio import Redis

from quack.canvas.board import BoardDoc
from quack.db import Db
from quack.events.event_types import AgentRequested
from quack.events.log import NewEvent, append_events
from quack.events.records import AgentParamsRecord

# WP12.4: a task of the teacher's turn has no solution space until its agent builds one.
ON_THE_FLY_SOURCE = "teacher"

_SESSION_OF_LEARNER = (
    "SELECT 1 AS found FROM core.events WHERE learner_id = %(learner_id)s "
    "AND type = 'session.started' AND payload ->> 'session_id' = %(session_id)s LIMIT 1"
)
_DOMAIN_OF_LEARNER = (
    "SELECT 1 AS found FROM core.events WHERE learner_id = %(learner_id)s "
    "AND type = 'domain.created' AND payload ->> 'domain_id' = %(domain_id)s LIMIT 1"
)
_TASK = (
    "SELECT source, solution_space IS NOT NULL AS has_space FROM content.tasks "
    "WHERE learner_id = %(learner_id)s AND task_id = %(task_id)s"
)
_COLUMNS = "canvas_id, session_id, task_id, doc, version, updated_at"
_INSERT = (
    "INSERT INTO content.canvas_boards (canvas_id, learner_id, session_id, task_id, doc) "
    "VALUES (%(canvas_id)s, %(learner_id)s, %(session_id)s, %(task_id)s, %(doc)s) "
    f"RETURNING {_COLUMNS}"
)
_CANVAS = (
    f"SELECT {_COLUMNS} FROM content.canvas_boards "
    "WHERE learner_id = %(learner_id)s AND canvas_id = %(canvas_id)s"
)
_CANVASES_OF_DOMAIN = (
    f"SELECT {_COLUMNS} FROM content.canvas_boards WHERE learner_id = %(learner_id)s "
    "AND session_id IN (SELECT (payload ->> 'session_id')::uuid FROM core.events "
    "WHERE learner_id = %(learner_id)s AND type = 'session.started' "
    "AND payload ->> 'domain_id' = %(domain_id)s) "
    "ORDER BY updated_at DESC, canvas_id"
)


class CanvasNotFound(Exception):
    """No such session, task, canvas or domain of this learner: 404."""


@dataclass(frozen=True)
class Canvas:
    canvas_id: UUID
    session_id: UUID | None
    task_id: UUID | None
    doc: BoardDoc
    version: int
    updated_at: datetime


async def open_canvas(
    db: Db,
    *,
    learner_id: UUID,
    session_id: UUID,
    task_id: UUID | None = None,
    redis: Redis | None = None,
) -> Canvas:
    """`POST /v1/sessions/{id}/canvases {task_id?}`."""
    if (
        await db.fetch_one(
            _SESSION_OF_LEARNER, {"learner_id": learner_id, "session_id": str(session_id)}
        )
        is None
    ):
        raise CanvasNotFound(f"session {session_id} not found")
    needs_space = False
    if task_id is not None:
        task = await db.fetch_one(_TASK, {"learner_id": learner_id, "task_id": task_id})
        if task is None:
            raise CanvasNotFound(f"task {task_id} not found")
        needs_space = task["source"] == ON_THE_FLY_SOURCE and not task["has_space"]
    canvas_id = uuid4()
    doc = BoardDoc.empty(task_id=task_id)
    async with db.transaction():
        row = await db.fetch_one(
            _INSERT,
            {
                "canvas_id": canvas_id,
                "learner_id": learner_id,
                "session_id": session_id,
                "task_id": task_id,
                "doc": Jsonb(doc.model_dump(mode="json")),
            },
        )
        if needs_space:
            request = AgentRequested(
                request_id=uuid4(),
                kind="solution_space",
                params=AgentParamsRecord(task_id=task_id),
                needed_in_session=True,
            )
            event = NewEvent(
                type="agent.requested",
                payload=request,
                actor="system",
                idempotency_key=f"canvas:{canvas_id}:solution_space",
                session_id=session_id,
            )
            await append_events(db, learner_id, [event], redis=redis)
    assert row is not None
    return _canvas(row)


async def get_canvas(db: Db, *, learner_id: UUID, canvas_id: UUID) -> Canvas:
    row = await db.fetch_one(_CANVAS, {"learner_id": learner_id, "canvas_id": canvas_id})
    if row is None:
        raise CanvasNotFound(f"canvas {canvas_id} not found")
    return _canvas(row)


async def domain_canvases(db: Db, *, learner_id: UUID, domain_id: UUID) -> list[Canvas]:
    """`GET /v1/domains/{id}/canvases`, the last changed first."""
    params = {"learner_id": learner_id, "domain_id": str(domain_id)}
    if await db.fetch_one(_DOMAIN_OF_LEARNER, params) is None:
        raise CanvasNotFound(f"domain {domain_id} not found")
    return [_canvas(row) for row in await db.fetch_all(_CANVASES_OF_DOMAIN, params)]


def _canvas(row: dict[str, Any]) -> Canvas:
    return Canvas(
        canvas_id=row["canvas_id"],
        session_id=row["session_id"],
        task_id=row["task_id"],
        doc=BoardDoc.model_validate(row["doc"]),
        version=row["version"],
        updated_at=row["updated_at"],
    )
