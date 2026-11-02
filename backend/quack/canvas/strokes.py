"""The stroke journal of a canvas (Т-§15.1, Т-§15.2, ТЗ Ф4 WP21.2).

Strokes are raw material, not events: the API keeps the client's batches in memory and writes a
chunk `learners/{id}/canvas/{session_id}/{chunk}-{ulid}.bin` every `stroke_chunk_seconds`.
A batch is acknowledged only after its chunk is written; a repeated `batch_no` is dropped; with
the store down nothing is acknowledged and the client sends again (Т-§20.7). Chunk format:
points as deltas `(dx, dy, dt, pressure)`, MessagePack, zstd. An erasure is an operation of
the journal, never a deletion.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from quack.storage.objects import ObjectStore


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
    raise NotImplementedError


def decode_chunk(data: bytes) -> list[StrokeBatch]:
    """The inverse of `encode_chunk` (replay, Т-§15.7)."""
    raise NotImplementedError


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

    def add(self, batch: StrokeBatch, *, now: datetime) -> bool:
        """Keep a batch until its chunk is written; `False` for a `batch_no` seen before."""
        raise NotImplementedError

    async def flush_due(self, *, now: datetime) -> list[int]:
        """Write a chunk if the oldest pending batch waited `chunk_seconds`; the acknowledged
        batch numbers (empty when nothing was due or the store is down)."""
        raise NotImplementedError

    async def flush(self) -> list[int]:
        """Write every pending batch now (the socket closes); acknowledged numbers."""
        raise NotImplementedError
