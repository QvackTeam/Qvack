"""The WebSocket of a canvas, `WS /v1/canvases/{id}/ws` (ТЗ Ф4 WP21.2; Т-§1.6, Т-§15.1, Т-§15.2).

Sign-in is the session cookie of the handshake: a `full` session of the canvas owner, or a
`companion` session paired to this canvas, which only receives the status (WP22.1): of the
server messages only `COMPANION_KINDS`, and any message it sends closes the socket with 1008
before it is read (D-C-124). Without a session the socket is refused with 1008; a malformed
client message closes it with 1007 (D-C-121).

`stroke_batch` goes to the stroke journal (`quack.canvas.strokes`): `ack {batch_no}` only after
the chunk with the batch is written; a repeated `batch_no` writes nothing and, once written, is
acknowledged again; with the store down nothing is acknowledged and the client repeats
(Т-§20.7). Pending batches are written on close. The messages of the server to every device of
the canvas, in any API process, go through Redis pub/sub `canvas:{id}` (`publish_canvas`);
without Redis a socket gets only its own acks (§4.2).

`line_ready`, `typed_formula`, `check_request` are accepted by the protocol here; recognition,
step checks and interventions handle them in WP21.3–21.5.
"""

from __future__ import annotations

import asyncio
import contextlib
from datetime import UTC, datetime
from typing import Annotated, Any, Literal
from uuid import UUID

import orjson
from fastapi import WebSocket, WebSocketDisconnect
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError
from redis.asyncio import Redis
from redis.exceptions import RedisError

from quack.api.auth import CurrentSession
from quack.api.resources import AppResources
from quack.canvas.boards import Canvas
from quack.canvas.strokes import (
    Erasure,
    Point,
    Stroke,
    StrokeBatch,
    StrokeJournal,
    chunk_max_batches,
)
from quack.logging import get_logger

log = get_logger(__name__)

# RFC 6455 §7.4.1: 1008 — policy violation (no session, a foreign canvas, a companion sending),
# 1007 — data inconsistent with the type of the message.
CLOSE_POLICY = 1008
CLOSE_INVALID = 1007

# WP22.1: the companion sees the status of its canvas "and nothing more". Of the server messages
# of WP21.2 only `task_closed` is a status; recognitions, marks, hints and layers are the
# content of the solution (D-C-124).
COMPANION_KINDS = frozenset({"task_closed"})


def canvas_channel(canvas_id: UUID) -> str:
    """Т-§15.2: one channel per canvas."""
    return f"canvas:{canvas_id}"


async def publish_canvas(redis: Redis, canvas_id: UUID, message: dict[str, Any]) -> None:
    """A server message (`line_recognized`, `mark`, `hint`, `layer_update`, `task_closed`) to
    every socket of the canvas in every API process."""
    await redis.publish(canvas_channel(canvas_id), orjson.dumps(message))


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class StrokeIn(_Strict):
    stroke_id: str
    # Absolute `(x, y, t_ms, pressure)`; the journal stores them as deltas (Т-§15.1).
    points: list[tuple[float, float, int, float]]


class ErasureIn(_Strict):
    stroke_ids: list[str]
    at_ms: int


class StrokeBatchIn(_Strict):
    type: Literal["stroke_batch"]
    batch_no: int = Field(ge=0)
    strokes: list[StrokeIn] = Field(default_factory=list[StrokeIn])
    erasures: list[ErasureIn] = Field(default_factory=list[ErasureIn])

    def batch(self) -> StrokeBatch:
        return StrokeBatch(
            batch_no=self.batch_no,
            strokes=tuple(
                Stroke(s.stroke_id, tuple(Point(*p) for p in s.points)) for s in self.strokes
            ),
            erasures=tuple(Erasure(tuple(e.stroke_ids), e.at_ms) for e in self.erasures),
        )


class LineReadyIn(_Strict):
    type: Literal["line_ready"]
    line_id: str
    stroke_ids: list[str]
    bbox: tuple[float, float, float, float]
    started_at: int
    ended_at: int


class TypedFormulaIn(_Strict):
    type: Literal["typed_formula"]
    block_id: str
    latex: str


class CheckRequestIn(_Strict):
    type: Literal["check_request"]


type ClientMessage = Annotated[
    StrokeBatchIn | LineReadyIn | TypedFormulaIn | CheckRequestIn, Field(discriminator="type")
]
_CLIENT_MESSAGE: TypeAdapter[ClientMessage] = TypeAdapter(ClientMessage)


def may_open(session: CurrentSession | None, canvas_id: UUID) -> bool:
    """A session may open the socket of the canvas: `full`, or `companion` of this canvas."""
    if session is None:
        return False
    return session.scope == "full" or session.canvas_id == canvas_id


async def serve_canvas(
    websocket: WebSocket, resources: AppResources, session: CurrentSession, canvas: Canvas
) -> None:
    """The accepted socket until the client leaves."""
    assert canvas.session_id is not None
    journal = StrokeJournal(
        resources.storage,
        learner_id=session.learner_id,
        session_id=canvas.session_id,
        chunk_seconds=resources.settings.stroke_chunk_seconds,
        max_batches=chunk_max_batches(resources.settings),
    )
    sending = asyncio.Lock()

    async def send(message: dict[str, Any]) -> None:
        async with sending:
            await websocket.send_json(message)

    async def acknowledge(batch_nos: list[int]) -> None:
        for batch_no in batch_nos:
            await send({"type": "ack", "batch_no": batch_no})

    relay = (
        asyncio.create_task(
            _relay(
                resources.redis,
                canvas.canvas_id,
                send,
                COMPANION_KINDS if session.scope == "companion" else None,
            )
        )
        if resources.redis is not None
        else None
    )
    try:
        while True:
            timeout = journal.due_in(now=datetime.now(UTC))
            try:
                text = await asyncio.wait_for(websocket.receive_text(), timeout)
            except TimeoutError:
                await acknowledge(await journal.flush_due(now=datetime.now(UTC)))
                continue
            if session.scope == "companion":
                await websocket.close(code=CLOSE_POLICY)  # the companion only gets the status
                return
            try:
                message = _CLIENT_MESSAGE.validate_json(text)
            except ValidationError:
                await websocket.close(code=CLOSE_INVALID)
                return
            if isinstance(message, StrokeBatchIn):
                if journal.written(message.batch_no):
                    await acknowledge([message.batch_no])
                else:
                    journal.add(message.batch(), now=datetime.now(UTC))
                    await acknowledge(await journal.flush_due(now=datetime.now(UTC)))
            else:
                log.info("canvas_message_pending", kind=message.type)  # WP21.3–21.5
    except WebSocketDisconnect:
        pass
    finally:
        if relay is not None:
            relay.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await relay
        await journal.flush()  # the client is gone: written, but nobody to acknowledge


async def _relay(redis: Redis, canvas_id: UUID, send: Any, kinds: frozenset[str] | None) -> None:
    """Messages of `canvas:{id}` to this socket (only `kinds` when given); a Redis failure ends
    the relay, not the socket."""
    pubsub = redis.pubsub()
    try:
        await pubsub.subscribe(canvas_channel(canvas_id))
        async for message in pubsub.listen():  # ends by cancellation when the socket closes
            if message["type"] != "message":
                continue
            payload = orjson.loads(message["data"])
            if kinds is None or payload.get("type") in kinds:
                await send(payload)
    except RedisError as exc:
        log.warning("canvas_relay_failed", canvas_id=str(canvas_id), error=str(exc))
    finally:
        with contextlib.suppress(RedisError):
            await asyncio.shield(pubsub.aclose())
