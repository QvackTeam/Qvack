"""The e2e stand `system` (ТЗ Фазы 3 WP10.1, contract of the stand's behaviour).

- `create_app` with all routers over real Postgres, Neo4j and Redis; the LLM is a
  `ScriptedLLMProvider`, compute is `httpx.MockTransport` with scripted verdicts;
- projector, dispatcher and job workers run as asyncio tasks in the same event loop
  and stop when the test ends;
- `await system.settle()` waits until the projector (and the dispatcher) caught up with the
  log of every learner and no claimable job is left: a deterministic sync point, not `sleep`;
- `pause_background()` / `resume_background()` stop and start projector and workers (law 9);

Wiring points owned by stream A are marked `# S-A:`. Handlers come from `quack.runtime`
(WP2.2) and get one `JobContext` over the stand's resources (WP2.1). There is no scheduler of
periodic jobs: the one of Phase 3 is removed with WP1.3 (D-A-224), the one of Phase 4 writes to
the Phase 4 queue, which this stand does not run.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import httpx
from fastapi import FastAPI
from neo4j import AsyncDriver
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from quack.api.app import create_app
from quack.api.auth import SESSION_COOKIE
from quack.api.resources import AppResources
from quack.auth.sessions import open_session
from quack.config import Settings
from quack.db import Db
from quack.db.postgres import SessionFactory
from quack.events.append import append_events
from quack.events.models import NewEvent
from quack.graph.worker import ProjectorWorker
from quack.jobs.dispatcher import Dispatcher
from quack.jobs.queue import ClaimedJob
from quack.jobs.runner import JobContext, JobHandler, JobRunner
from quack.runtime import register_all_handlers
from tests.support.compute import ComputeScenario, scripted_compute
from tests.support.llm import ScriptedLLMProvider
from tests.support.resources import build_app_resources

SETTLE_POLL_SEC = 0.05
SETTLE_STABLE_ROUNDS = 2

# Learners whose projection or dispatch lags, and jobs that can still be claimed now.
_BUSY_SQL = text(
    """
    SELECT
      (SELECT count(*) FROM core.learner_seq s
         LEFT JOIN ops.projector_offsets p ON p.learner_id = s.learner_id
        WHERE s.last_seq > coalesce(p.applied_seq, 0)) AS projector_lagging,
      (SELECT count(*) FROM core.learner_seq s
         LEFT JOIN ops.dispatcher_offsets d ON d.learner_id = s.learner_id
        WHERE s.last_seq > coalesce(d.last_dispatched_seq, 0)) AS dispatcher_lagging,
      (SELECT count(*) FROM ops.jobs
        WHERE status = 'running' OR (status = 'queued' AND run_after <= now())) AS jobs_ready
    """
)


@dataclass(frozen=True)
class JobStart:
    """Stand log: a job handler started while the learner's projection stood at `applied_seq`."""

    job_id: UUID
    kind: str
    learner_id: UUID | None
    applied_seq: int


_APPLIED_SQL = text("SELECT applied_seq FROM ops.projector_offsets WHERE learner_id = :l")


def job_handlers() -> dict[str, JobHandler]:
    """All job handlers, registered as the `workers` process does (WP2.2). The completeness
    check is `T-Q7`'s; here a missing handler leaves its jobs queued and the test that needs
    them fails on its own assertion."""
    return register_all_handlers()


def job_context(resources: AppResources) -> JobContext:
    """The `workers` resources of §4.2 over the stand's ones: one process, one set (WP2.1)."""
    return JobContext(
        settings=resources.settings,
        db=resources.db,
        session_factory=resources.session_factory,
        engine=resources.engine,
        neo4j=resources.neo4j,
        redis=resources.redis,
        llm=resources.llm,
        compute=resources.compute,
        storage=resources.storage,
        embeddings=resources.embeddings,
        deletions=resources.deletions,
    )


def _logged(handler: JobHandler, log: list[JobStart]) -> JobHandler:
    async def run(job: ClaimedJob, ctx: JobContext) -> None:
        applied = 0
        if job.learner_id is not None:
            async with ctx.session_factory() as session:
                applied = int(await session.scalar(_APPLIED_SQL, {"l": job.learner_id}) or 0)
        log.append(JobStart(job.id, job.kind, job.learner_id, applied))
        await handler(job, ctx)

    return run


@dataclass
class System:
    settings: Settings
    engine: AsyncEngine
    session_factory: SessionFactory
    neo4j: AsyncDriver
    redis: Redis | None
    llm: ScriptedLLMProvider
    compute: ComputeScenario
    resources: AppResources
    app: FastAPI
    client: httpx.AsyncClient
    job_starts: list[JobStart] = field(default_factory=list)
    _stop: asyncio.Event = field(default_factory=asyncio.Event)
    _tasks: list[asyncio.Task[None]] = field(default_factory=list)

    # --- background ---------------------------------------------------------------------

    def _spawn(self, factory: Callable[[asyncio.Event], Coroutine[Any, Any, None]]) -> None:
        self._tasks.append(asyncio.create_task(factory(self._stop)))

    def start_background(self) -> None:
        if self._tasks:
            return
        self._stop = asyncio.Event()
        projector = ProjectorWorker(
            self.settings, self.engine, self.session_factory, self.neo4j, self.redis
        )
        self._spawn(projector.run_forever)
        # Dispatcher of the log (WP11.1), as `quack.cli worker` runs it.
        dispatcher = Dispatcher(self.settings, self.session_factory, self.redis)
        self._spawn(dispatcher.run_forever)
        handlers = {k: _logged(h, self.job_starts) for k, h in job_handlers().items()}
        runner = JobRunner(
            self.settings,
            self.session_factory,
            f"e2e-{uuid4().hex[:8]}",
            handlers=handlers,
            context=job_context(self.resources),
        )
        self._spawn(runner.run_forever)

    async def stop_background(self) -> None:
        self._stop.set()
        tasks, self._tasks = self._tasks, []
        for task in tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task

    async def pause_background(self) -> None:
        await self.stop_background()

    def resume_background(self) -> None:
        self.start_background()

    async def settle(self, timeout_s: float = 30.0) -> None:
        """Wait until the log is projected (and dispatched) and no claimable job is left."""
        deadline = time.monotonic() + timeout_s
        stable = 0
        last: tuple[int, int, int] = (-1, -1, -1)
        while True:
            for task in self._tasks:
                if task.done() and task.exception() is not None:
                    raise AssertionError(f"background task failed: {task.exception()!r}")
            async with self.session_factory() as session:
                row = (await session.execute(_BUSY_SQL)).one()
            last = (
                int(row.projector_lagging),
                int(row.dispatcher_lagging),
                int(row.jobs_ready),
            )
            stable = stable + 1 if last == (0, 0, 0) else 0
            if stable >= SETTLE_STABLE_ROUNDS:
                return
            if time.monotonic() > deadline:
                raise AssertionError(
                    f"system did not settle in {timeout_s} s: projector lagging learners "
                    f"{last[0]}, dispatcher lagging learners {last[1]}, claimable jobs {last[2]}"
                )
            await asyncio.sleep(SETTLE_POLL_SEC)

    # --- HTTP helpers -------------------------------------------------------------------

    async def register(self) -> Learner:
        """A new learner signed in with a Phase 4 session (ТЗ Ф4 WP18.3, D-A-113).
        `/v1/auth/register` is removed; until the Phase 3 routes move to `Db` (WP1.3) the
        account is the rows the removed route wrote: `auth.users` and `learner.registered` in
        the Phase 3 log, plus `core.learners` of Phase 4."""
        learner_id = uuid4()
        email = f"e2e-{learner_id.hex[:12]}@example.com"
        async with self.session_factory() as session, session.begin():
            await session.execute(
                text(
                    "INSERT INTO auth.users (id, email, password_hash) VALUES (:id, :email, '!e2e')"
                ),
                {"id": learner_id, "email": email},
            )
            await append_events(
                session,
                learner_id,
                [
                    NewEvent(
                        type="learner.registered",
                        actor="learner",
                        idempotency_key=f"register:{learner_id}",
                        payload={"email": email, "display_name": None, "preferences": {}},
                    )
                ],
                publish_wakeup=False,
            )
        await self.resources.db.execute(
            "INSERT INTO core.learners (learner_id, email) VALUES (%(learner_id)s, %(email)s)",
            {"learner_id": learner_id, "email": email},
        )
        cookie = await open_session(
            self.resources.db, self.settings, learner_id=learner_id, now=datetime.now(UTC)
        )
        headers = {"Cookie": f"{SESSION_COOKIE}={cookie}"}
        # WP18.4: a session starts only after `consent.given {kind: terms}` of the current
        # `terms_version`; the learner of the stand accepts it as the client would.
        consent = await self.client.post(
            "/v1/consents",
            json={
                "kind": "terms",
                "version": self.settings.terms_version,
                "idempotency_key": f"terms:{learner_id}",
            },
            headers=headers,
        )
        assert consent.status_code == 200, consent.text
        return Learner(learner_id, email, headers)


# A test value of `terms_version` (the real one is the owner's, D-C-105).
E2E_TERMS_VERSION = "e2e-terms"


@dataclass(frozen=True)
class Learner:
    learner_id: UUID
    email: str
    headers: dict[str, str]


async def build_system(
    settings: Settings,
    engine: AsyncEngine,
    session_factory: SessionFactory,
    neo4j: AsyncDriver,
    redis: Redis | Any | None,
    db: Db,
) -> System:
    # D-C-105: `terms_version` is the owner's value and is unset by default; the stand needs
    # one so that its learners can accept the terms (WP18.4).
    if settings.terms_version is None:
        settings = settings.model_copy(update={"terms_version": E2E_TERMS_VERSION})
    llm = ScriptedLLMProvider()
    compute = ComputeScenario()
    resources = build_app_resources(
        settings,
        engine,
        neo4j,
        redis,
        db=db,
        session_factory=session_factory,
        provider=llm,
        compute=scripted_compute(compute),
    )
    app = create_app(settings, resources=resources)
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
    return System(
        settings=settings,
        engine=engine,
        session_factory=session_factory,
        neo4j=neo4j,
        redis=redis,
        llm=llm,
        compute=compute,
        resources=resources,
        app=app,
        client=client,
    )
