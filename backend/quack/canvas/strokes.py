"""The stroke journal of a canvas (Т-§15.1, Т-§15.2, ТЗ Ф4 WP21.2).

Strokes are raw material, not events: the API keeps the client's batches in memory and writes a
chunk `learners/{id}/canvas/{session_id}/{chunk}-{ulid}.bin` every `stroke_chunk_seconds`.
A batch is acknowledged only after its chunk is written; a repeated `batch_no` is dropped; with
the store down nothing is acknowledged and the client sends again (Т-§20.7). Chunk format:
points as deltas `(dx, dy, dt, pressure)`, MessagePack, zstd. An erasure is an operation of
the journal, never a deletion.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

import msgpack
import zstandard

from quack.storage.keys import canvas_chunk_key
from quack.storage.objects import ObjectStore, StorageUnavailable

CHUNK_CONTENT_TYPE = "application/octet-stream"


@dataclass(frozen=True)
class Point:
    x: float
    y: float
    t_ms: int
    pressure: float


@dataclass(frozen=True)
class Stroke:
    stroke_id: str
    points: tuple[Point, ...]


@dataclass(frozen=True)
class Erasure:
    """The learner erased these strokes at `at_ms` (device time)."""

    stroke_ids: tuple[str, ...]
    at_ms: int


@dataclass(frozen=True)
class StrokeBatch:
    batch_no: int
    strokes: tuple[Stroke, ...] = ()
    erasures: tuple[Erasure, ...] = ()


def encode_chunk(batches: list[StrokeBatch]) -> bytes:
    """Batches → MessagePack with delta points, compressed by zstd."""
    payload = {"batches": [_batch_to_raw(batch) for batch in batches]}
    packed = msgpack.packb(payload, use_bin_type=True)
    assert isinstance(packed, bytes)
    return zstandard.ZstdCompressor().compress(packed)


def decode_chunk(data: bytes) -> list[StrokeBatch]:
    """The inverse of `encode_chunk` (replay, Т-§15.7)."""
    raw = msgpack.unpackb(zstandard.ZstdDecompressor().decompress(data), raw=False)
    return [_batch_from_raw(item) for item in raw["batches"]]


def _batch_to_raw(batch: StrokeBatch) -> dict[str, Any]:
    return {
        "batch_no": batch.batch_no,
        "strokes": [
            {"stroke_id": stroke.stroke_id, "points": _deltas(stroke.points)}
            for stroke in batch.strokes
        ],
        "erasures": [
            {"stroke_ids": list(erasure.stroke_ids), "at_ms": erasure.at_ms}
            for erasure in batch.erasures
        ],
    }


def _batch_from_raw(raw: dict[str, Any]) -> StrokeBatch:
    return StrokeBatch(
        batch_no=raw["batch_no"],
        strokes=tuple(
            Stroke(stroke_id=item["stroke_id"], points=_points(item["points"]))
            for item in raw["strokes"]
        ),
        erasures=tuple(
            Erasure(stroke_ids=tuple(item["stroke_ids"]), at_ms=item["at_ms"])
            for item in raw["erasures"]
        ),
    )


def _deltas(points: tuple[Point, ...]) -> list[list[float | int]]:
    """The first point absolute, the next ones as `(dx, dy, dt, pressure)`."""
    out: list[list[float | int]] = []
    previous: Point | None = None
    for point in points:
        if previous is None:
            out.append([point.x, point.y, point.t_ms, point.pressure])
        else:
            out.append(
                [
                    point.x - previous.x,
                    point.y - previous.y,
                    point.t_ms - previous.t_ms,
                    point.pressure,
                ]
            )
        previous = point
    return out


def _points(raw: list[list[float | int]]) -> tuple[Point, ...]:
    points: list[Point] = []
    for x, y, t, pressure in raw:
        if points:
            last = points[-1]
            points.append(Point(last.x + x, last.y + y, last.t_ms + int(t), float(pressure)))
        else:
            points.append(Point(float(x), float(y), int(t), float(pressure)))
    return tuple(points)


class StrokeJournal:
    """Pending batches of one canvas in one API process."""

    def __init__(
        self,
        storage: ObjectStore,
        *,
        learner_id: UUID,
        session_id: UUID,
        chunk_seconds: int,
    ) -> None:
        self._storage = storage
        self._learner_id = learner_id
        self._session_id = session_id
        self._chunk_seconds = chunk_seconds
        self._state = _JournalState()

    def add(self, batch: StrokeBatch, *, now: datetime) -> bool:
        """Keep a batch until its chunk is written; `False` for a `batch_no` seen before."""
        state = self._state
        if batch.batch_no in state.seen:
            return False
        state.seen.add(batch.batch_no)
        if not state.pending:
            state.oldest_at = now
        state.pending.append(batch)
        return True

    async def flush_due(self, *, now: datetime) -> list[int]:
        """Write a chunk if the oldest pending batch waited `chunk_seconds`; the acknowledged
        batch numbers (empty when nothing was due or the store is down)."""
        state = self._state
        if not state.pending or state.oldest_at is None:
            return []
        if now - state.oldest_at < timedelta(seconds=self._chunk_seconds):
            return []
        return await self.flush()

    async def flush(self) -> list[int]:
        """Write every pending batch now (the socket closes); acknowledged numbers."""
        state = self._state
        if not state.pending:
            return []
        batches = list(state.pending)
        key = canvas_chunk_key(self._learner_id, self._session_id, state.next_chunk)
        try:
            await self._storage.put(key, encode_chunk(batches), CHUNK_CONTENT_TYPE)
        except StorageUnavailable:
            return []  # no ack: the batches stay pending, the client repeats (Т-§20.7)
        state.next_chunk += 1
        state.pending = state.pending[len(batches) :]
        state.oldest_at = None
        return [batch.batch_no for batch in batches]


@dataclass
class _JournalState:
    seen: set[int] = field(default_factory=set[int])
    pending: list[StrokeBatch] = field(default_factory=list[StrokeBatch])
    oldest_at: datetime | None = None
    next_chunk: int = 0
