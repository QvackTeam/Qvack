"""`read_consistent_slice` (spec §8.2, Т-§2.6): reads with a watermark and the fallback when
the projector lags (D-A-228).

The overlay of the session over a lagging projection (`build_session_overlay`) was a function of
Phase 3: it read the journal through `AsyncSession` and applied the handlers of Phase 3; its two
tests are removed with it (D-A-228). The waiting for the tail of the journal on `Db` is checked in
`graph/test_projection_runner.py::test_slice_waits_for_the_journal_of_phase_4`.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any
from uuid import UUID, uuid4

from redis.asyncio import Redis

from quack.graph.slice import SliceDeps, read_consistent_slice


def _deps(redis: Redis | None, applied: dict[str, int]) -> SliceDeps:
    async def reader(learner_id: UUID) -> int:
        return applied.get(str(learner_id), 0)

    return SliceDeps(redis=redis, applied_seq_reader=reader)


async def test_slice_returns_immediately_when_caught_up(redis: Redis) -> None:
    learner = uuid4()
    applied = {str(learner): 5}
    calls: list[int] = []

    async def loader() -> dict[str, Any]:
        calls.append(1)
        return {"ok": True}

    result = await read_consistent_slice(learner, 5, loader, 2000, deps=_deps(redis, applied))
    assert result.data == {"ok": True}
    assert result.lag_degraded is False and result.stable is True
    assert result.applied_seq == 5 and len(calls) == 1


async def test_slice_waits_for_projector_applied_signal(redis: Redis) -> None:
    learner = uuid4()
    applied = {str(learner): 3}

    async def loader() -> int:
        return applied[str(learner)]

    async def projector_catches_up() -> None:
        await asyncio.sleep(0.2)
        applied[str(learner)] = 7
        await redis.publish(f"projector:applied:{learner}", json.dumps({"applied_seq": 7}))

    started = time.monotonic()
    task = asyncio.create_task(projector_catches_up())
    result = await read_consistent_slice(learner, 7, loader, 3000, deps=_deps(redis, applied))
    await task
    assert result.lag_degraded is False
    assert result.data == 7 and result.applied_seq == 7
    assert time.monotonic() - started < 2.5


async def test_slice_degrades_after_timeout(redis: Redis) -> None:
    learner = uuid4()

    async def loader() -> str:
        return "stale"

    started = time.monotonic()
    result = await read_consistent_slice(
        learner, 10, loader, 300, deps=_deps(redis, {str(learner): 2})
    )
    elapsed = time.monotonic() - started
    assert result.lag_degraded is True
    assert result.data == "stale" and result.applied_seq == 2
    assert 0.25 <= elapsed < 2.0


async def test_slice_degrades_without_redis() -> None:
    learner = uuid4()

    async def loader() -> str:
        return "stale"

    result = await read_consistent_slice(
        learner, 10, loader, 200, deps=_deps(None, {str(learner): 2})
    )
    assert result.lag_degraded is True


async def test_slice_retries_until_watermark_is_stable(redis: Redis) -> None:
    learner = uuid4()
    applied = {str(learner): 5}

    async def loader() -> str:
        # The projector commits while we read: the watermark moves once.
        if applied[str(learner)] == 5:
            applied[str(learner)] = 6
        return f"slice@{applied[str(learner)]}"

    result = await read_consistent_slice(learner, 5, loader, 2000, deps=_deps(redis, applied))
    assert result.stable is True
    assert result.data == "slice@6" and result.applied_seq == 6
