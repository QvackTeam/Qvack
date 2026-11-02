"""WP21.2: the stroke journal (ТЗ Ф4 §8.12 `T-CV1`, `T-CV2`; Т-§15.1, Т-§15.2, Т-§20.7)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import msgpack
import zstandard

from quack.canvas.strokes import (
    Erasure,
    Point,
    Stroke,
    StrokeBatch,
    StrokeJournal,
    decode_chunk,
    encode_chunk,
)
from tests.support.storage import BrokenObjectStore, InMemoryObjectStore

NOW = datetime(2026, 11, 2, 12, 0, tzinfo=UTC)
ZSTD_MAGIC = b"\x28\xb5\x2f\xfd"


def _batch(no: int, stroke: str = "s1") -> StrokeBatch:
    points = (
        Point(10.0, 20.0, 1000, 0.5),
        Point(12.5, 21.0, 1016, 0.6),
        Point(15.0, 23.0, 1033, 0.7),
    )
    return StrokeBatch(batch_no=no, strokes=(Stroke(f"{stroke}-{no}", points),))


# --- T-CV2 -----------------------------------------------------------------------------------


def test_chunk_format() -> None:
    """T-CV2: MessagePack + zstd, points as deltas; an erasure is an operation."""
    batches = [_batch(1), StrokeBatch(batch_no=2, erasures=(Erasure(("s1-1",), 2000),))]
    data = encode_chunk(batches)
    assert data[:4] == ZSTD_MAGIC
    raw = msgpack.unpackb(zstandard.ZstdDecompressor().decompress(data), raw=False)
    [first, second] = raw["batches"]
    points = first["strokes"][0]["points"]
    assert points[0] == [10.0, 20.0, 1000, 0.5]  # the first point is absolute
    assert points[1] == [2.5, 1.0, 16, 0.6]  # the next ones are deltas (dx, dy, dt, pressure)
    assert second["erasures"] == [{"stroke_ids": ["s1-1"], "at_ms": 2000}]
    assert decode_chunk(data) == batches


# --- T-CV1 -----------------------------------------------------------------------------------


def _journal(storage: object, chunk_seconds: int = 10) -> StrokeJournal:
    return StrokeJournal(
        storage,  # type: ignore[arg-type]
        learner_id=uuid4(),
        session_id=uuid4(),
        chunk_seconds=chunk_seconds,
    )


async def test_stroke_ack_after_write() -> None:
    """T-CV1: `ack` only after the chunk is written; a repeated `batch_no` is dropped."""
    storage = InMemoryObjectStore()
    journal = _journal(storage)
    assert journal.add(_batch(1), now=NOW) is True
    assert journal.add(_batch(2), now=NOW + timedelta(seconds=3)) is True
    assert await journal.flush_due(now=NOW + timedelta(seconds=9)) == []
    assert storage.objects == {}

    assert await journal.flush_due(now=NOW + timedelta(seconds=10)) == [1, 2]
    [key] = storage.objects
    assert "/canvas/" in key and key.endswith(".bin")
    assert [b.batch_no for b in decode_chunk(storage.objects[key][0])] == [1, 2]

    # The client did not get the ack and sends batch 2 again: dropped, nothing new is written.
    assert journal.add(_batch(2), now=NOW + timedelta(seconds=11)) is False
    assert await journal.flush_due(now=NOW + timedelta(seconds=30)) == []
    assert len(storage.objects) == 1


async def test_store_down_gives_no_ack_and_keeps_batches() -> None:
    """T-CV1, Т-§20.7: the store is down — no `ack`, the batches wait for the next write."""
    journal = _journal(BrokenObjectStore())
    journal.add(_batch(1), now=NOW)
    assert await journal.flush_due(now=NOW + timedelta(seconds=10)) == []
    working = InMemoryObjectStore()
    journal._storage = working  # the store is back  # pyright: ignore[reportPrivateUsage]
    assert await journal.flush_due(now=NOW + timedelta(seconds=11)) == [1]
    assert len(working.objects) == 1


async def test_flush_writes_everything_and_chunks_get_new_keys() -> None:
    """Closing the socket writes the rest; each chunk is a new immutable object (Т-§3.3)."""
    storage = InMemoryObjectStore()
    journal = _journal(storage)
    journal.add(_batch(1), now=NOW)
    assert await journal.flush() == [1]
    journal.add(_batch(2), now=NOW)
    assert await journal.flush() == [2]
    assert await journal.flush() == []
    assert len(storage.objects) == 2
