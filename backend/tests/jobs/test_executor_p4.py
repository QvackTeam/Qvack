"""ТЗ Ф4 WP7.4: the executor on the queue of Phase 4 — the pulse and the cancel (T-D6), the end of
a handler (success, retry, defer, permanent failure — T-D8), shutdown, a lost job, the worker loop.
Needs Postgres only."""

from __future__ import annotations

import asyncio
from uuid import UUID, uuid4

import pytest

from quack.config import Settings
from quack.db import Db
from quack.jobs import queue_p4 as q
from quack.jobs.executor_p4 import JobWorker, run_claimed
from quack.jobs.queue import JobDeferred, JobFailedPermanently
from quack.jobs.rules_p4 import JobPlan
from tests.db.fixtures import create_learner

SETTINGS = Settings(job_heartbeat_interval_sec=1, job_max_attempts=2, consumer_poll_ms=50)


async def _put(db: Db, learner: UUID, key: str = "a", **extra: object) -> q.ClaimedJob:
    plan = JobPlan(
        kind="agent.viz",
        job_key=key,
        priority_class="P2",
        learner_id=learner,
        **extra,  # type: ignore[arg-type]
    )
    await q.enqueue(db, plan)
    job = await q.claim_next(db, SETTINGS)
    assert job is not None
    return job


async def _status(db: Db, key: str = "a") -> str:
    row = await db.fetch_one("SELECT status FROM ops.jobs WHERE job_key = %(k)s", {"k": key})
    assert row is not None
    return row["status"]


async def test_a_finished_handler_succeeds(jobs_db: Db) -> None:
    learner = await create_learner(jobs_db)
    job = await _put(jobs_db, learner)
    ran = []

    async def work() -> None:
        ran.append(1)

    assert await run_claimed(jobs_db, SETTINGS, job, work) == "succeeded"
    assert ran and await _status(jobs_db) == "succeeded"


async def test_cancel_requested_is_seen_at_the_pulse_and_stops_the_task(jobs_db: Db) -> None:
    """T-D6: a running job gets `cancel_requested`, sees it at the pulse, the task is
    cancelled, the job ends `cancelled`."""
    learner = await create_learner(jobs_db)
    request = uuid4()
    job = await _put(jobs_db, learner, payload={"request_id": str(request)})
    started, cancelled = asyncio.Event(), asyncio.Event()

    async def work() -> None:
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise

    running = asyncio.create_task(run_claimed(jobs_db, SETTINGS, job, work))
    await started.wait()
    outcome = await q.request_cancel(jobs_db, learner, [request])
    assert outcome.requested == 1
    assert await asyncio.wait_for(running, timeout=5) == "cancelled"
    assert cancelled.is_set()
    assert await _status(jobs_db) == "cancelled"


async def test_a_job_the_cleaner_took_away_stops_without_writing(jobs_db: Db) -> None:
    learner = await create_learner(jobs_db)
    job = await _put(jobs_db, learner)
    started = asyncio.Event()

    async def work() -> None:
        started.set()
        await asyncio.Event().wait()

    running = asyncio.create_task(run_claimed(jobs_db, SETTINGS, job, work))
    await started.wait()
    await jobs_db.execute("UPDATE ops.jobs SET heartbeat_at = now() - interval '5 minutes'")
    assert await q.reap_stale(jobs_db, SETTINGS) == 1
    assert await asyncio.wait_for(running, timeout=5) == "lost"
    assert await _status(jobs_db) == "queued"  # the cleaner's decision stands


async def test_a_failing_handler_is_retried_then_failed_with_the_event(jobs_db: Db) -> None:
    """T-D8 through the executor: `job_max_attempts` = 2."""
    learner = await create_learner(jobs_db)
    session = uuid4()
    first = await _put(jobs_db, learner, session_id=session)

    async def broken() -> None:
        raise RuntimeError("model said no")

    assert await run_claimed(jobs_db, SETTINGS, first, broken) == "retried"
    assert await _status(jobs_db) == "queued"
    await jobs_db.execute("UPDATE ops.jobs SET run_at = now()")
    second = await q.claim_next(jobs_db, SETTINGS)
    assert second is not None and second.attempts == 2
    assert await run_claimed(jobs_db, SETTINGS, second, broken) == "failed"
    assert await _status(jobs_db) == "failed"
    (event,) = await jobs_db.fetch_all(
        "SELECT type, session_id, payload FROM core.events WHERE learner_id = %(l)s",
        {"l": learner},
    )
    assert event["type"] == "agent.completed" and event["session_id"] == session
    assert event["payload"]["ok"] is False and "model said no" in event["payload"]["error"]


async def test_permanent_failure_and_deferral(jobs_db: Db) -> None:
    learner = await create_learner(jobs_db)
    job = await _put(jobs_db, learner)

    async def later() -> None:
        raise JobDeferred(3600, "daily budget")

    assert await run_claimed(jobs_db, SETTINGS, job, later) == "deferred"
    row = await jobs_db.fetch_one("SELECT status, attempts, last_error FROM ops.jobs")
    assert row is not None
    assert (row["status"], row["attempts"], row["last_error"]) == ("queued", 0, "daily budget")

    await jobs_db.execute("UPDATE ops.jobs SET run_at = now()")
    again = await q.claim_next(jobs_db, SETTINGS)
    assert again is not None

    async def never() -> None:
        raise JobFailedPermanently("session budget")

    assert await run_claimed(jobs_db, SETTINGS, again, never) == "failed"
    assert await _status(jobs_db) == "failed"
    (event,) = await jobs_db.fetch_all("SELECT payload FROM core.events")
    assert event["payload"]["error"] == "session budget"


async def test_shutdown_returns_the_job_to_the_queue(jobs_db: Db) -> None:
    learner = await create_learner(jobs_db)
    job = await _put(jobs_db, learner)
    started = asyncio.Event()

    async def work() -> None:
        started.set()
        await asyncio.Event().wait()

    running = asyncio.create_task(run_claimed(jobs_db, SETTINGS, job, work))
    await started.wait()
    running.cancel()
    with pytest.raises(asyncio.CancelledError):
        await running
    row = await jobs_db.fetch_one("SELECT status, attempts FROM ops.jobs")
    assert row is not None and (row["status"], row["attempts"]) == ("queued", 0)


async def test_worker_runs_only_kinds_with_a_handler_and_admission(jobs_db: Db) -> None:
    learner = await create_learner(jobs_db)
    for key, kind in (("v", "agent.viz"), ("t", "task.check"), ("n", "embedding.compute")):
        await q.enqueue(
            jobs_db, JobPlan(kind=kind, job_key=key, priority_class="P2", learner_id=learner)
        )
    seen: list[str] = []

    async def handler(job: q.ClaimedJob) -> None:
        seen.append(job.kind)

    async def admission() -> list[str]:
        return ["agent.viz", "embedding.compute"]  # task.check's model is under pressure

    worker = JobWorker(
        SETTINGS,
        jobs_db,
        {"agent.viz": handler, "task.check": handler},
        admission=admission,
    )
    assert await worker.run_one() is True
    assert await worker.run_one() is False  # embedding.compute has no handler here
    assert seen == ["agent.viz"]
    assert await _status(jobs_db, "t") == "queued" and await _status(jobs_db, "n") == "queued"


async def test_worker_loop_runs_jobs_and_stops_on_the_event(jobs_db: Db) -> None:
    learner = await create_learner(jobs_db)
    for i in range(3):
        await q.enqueue(
            jobs_db,
            JobPlan(kind="agent.viz", job_key=f"j{i}", priority_class="P2", learner_id=learner),
        )
    done = asyncio.Event()
    count = 0

    async def handler(_job: q.ClaimedJob) -> None:
        nonlocal count
        count += 1
        if count == 3:
            done.set()

    async def admission() -> list[str]:
        return ["agent.viz"]

    worker = JobWorker(
        SETTINGS.model_copy(update={"worker_concurrency": 2}),
        jobs_db,
        {"agent.viz": handler},
        admission=admission,
    )
    stop = asyncio.Event()
    loop = asyncio.create_task(worker.run_forever(stop))
    await asyncio.wait_for(done.wait(), timeout=10)
    stop.set()
    await asyncio.wait_for(loop, timeout=10)
    rows = await jobs_db.fetch_all("SELECT status FROM ops.jobs")
    assert [r["status"] for r in rows] == ["succeeded"] * 3
