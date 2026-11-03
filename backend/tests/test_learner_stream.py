"""`GET /v1/learner/stream` — the learner change channel (ТЗ Фазы 3 WP7, `Т-§1.6`, T-H4)."""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from neo4j import AsyncDriver
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine

from quack.api.app import create_app
from quack.config import Settings
from quack.db import Db
from quack.db.postgres import SessionFactory
from quack.db.redis import learner_signal_channel, projector_applied_channel
from quack.events import append_events
from quack.events.log import NewEvent as P4Event
from quack.events.log import append_events as p4_append
from quack.graph.worker import ProjectorWorker
from tests.db.fixtures import create_learner
from tests.factories import new_event
from tests.support.auth import ensure_user, session_cookie, session_token
from tests.support.broken import BrokenRedis
from tests.support.resources import build_app_resources
from tests.support.sse import KEEPALIVE, StreamingASGITransport, next_sse_block, next_sse_event


@pytest.fixture
def stream_settings(settings: Settings) -> Settings:
    return settings.model_copy(update={"learner_stream_poll_ms": 50, "sse_keepalive_s": 15.0})


async def _learner(
    db: SessionFactory, pg_db: Db, settings: Settings
) -> tuple[UUID, dict[str, str]]:
    learner = uuid4()
    await ensure_user(db, learner)
    return learner, session_cookie(await session_token(pg_db, learner, settings))


async def _append(db: SessionFactory, learner: UUID, n: int) -> None:
    async with db() as session, session.begin():
        await append_events(
            session,
            learner,
            [new_event("learner.preferences_updated", {"preferences": {"i": i}}) for i in range(n)],
            publish_wakeup=False,
        )


def _client(app: Any) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=StreamingASGITransport(app), base_url="http://test")


async def _subscribers(redis: Redis, channel: str) -> int:
    return int(dict(await redis.pubsub_numsub(channel)).get(channel, 0))


async def _wait_subscribers(redis: Redis, channel: str, expected: int) -> None:
    async with asyncio.timeout(3.0):
        while True:
            if await _subscribers(redis, channel) == expected:
                return
            await asyncio.sleep(0.01)


async def test_learner_stream(
    stream_settings: Settings,
    pg_engine: AsyncEngine,
    db: SessionFactory,
    pg_db: Db,
    neo4j: AsyncDriver,
    redis: Redis,
) -> None:
    """T-H4 (Redis): first `projection_advanced` with current `applied_seq` and `last_seq`;
    an event projected by the projector → `projection_advanced` with the new `applied_seq`;
    after the client disconnects there are no subscriptions on `projector:applied:{id}`."""
    learner, headers = await _learner(db, pg_db, stream_settings)
    await _append(db, learner, 2)
    worker = ProjectorWorker(stream_settings, pg_engine, db, neo4j, redis)
    await worker.run_once()
    await _append(db, learner, 1)  # last_seq 3, applied 2

    resources = build_app_resources(
        stream_settings, pg_engine, neo4j, redis, db=pg_db, session_factory=db
    )
    app = create_app(stream_settings, resources=resources)
    channel = projector_applied_channel(learner)
    async with (
        _client(app) as client,
        client.stream("GET", "/v1/learner/stream", headers=headers) as r,
    ):
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        lines = r.aiter_lines()
        assert await next_sse_event(lines) == (
            "projection_advanced",
            {"applied_seq": 2, "last_seq": 3},
        )
        await _wait_subscribers(redis, channel, 1)
        await worker.run_once()
        assert await next_sse_event(lines) == ("projection_advanced", {"applied_seq": 3})
    await _wait_subscribers(redis, channel, 0)


async def test_learner_stream_polls_without_redis(
    stream_settings: Settings,
    pg_engine: AsyncEngine,
    db: SessionFactory,
    pg_db: Db,
    neo4j: AsyncDriver,
    redis: Redis,
) -> None:
    """T-H4 (broken Redis): the same events arrive by polling `ops.projector_offsets`, and only
    when `applied_seq` grows."""
    learner, headers = await _learner(db, pg_db, stream_settings)
    resources = build_app_resources(
        stream_settings, pg_engine, neo4j, BrokenRedis(), db=pg_db, session_factory=db
    )
    app = create_app(stream_settings, resources=resources)
    worker = ProjectorWorker(stream_settings, pg_engine, db, neo4j, redis)
    async with (
        _client(app) as client,
        client.stream("GET", "/v1/learner/stream", headers=headers) as r,
    ):
        lines = r.aiter_lines()
        assert await next_sse_event(lines) == (
            "projection_advanced",
            {"applied_seq": 0, "last_seq": 0},
        )
        await _append(db, learner, 2)
        await worker.run_once()
        assert await next_sse_event(lines) == ("projection_advanced", {"applied_seq": 2})
        with pytest.raises(TimeoutError):  # no growth → no event
            await next_sse_event(lines, timeout_s=0.3)


async def test_learner_stream_keepalive(
    stream_settings: Settings,
    pg_engine: AsyncEngine,
    db: SessionFactory,
    pg_db: Db,
    neo4j: AsyncDriver,
    redis: Redis,
) -> None:
    """WP6.3 for this stream: a silent channel sends `: ping` comments every `sse_keepalive_s`."""
    cfg = stream_settings.model_copy(update={"sse_keepalive_s": 0.2})
    learner, headers = await _learner(db, pg_db, cfg)
    resources = build_app_resources(cfg, pg_engine, neo4j, redis, db=pg_db, session_factory=db)
    async with (
        _client(create_app(cfg, resources=resources)) as client,
        client.stream("GET", "/v1/learner/stream", headers=headers) as r,
    ):
        lines = r.aiter_lines()
        assert (await next_sse_block(lines))[0] == "projection_advanced"
        assert await next_sse_block(lines) == KEEPALIVE
        assert await next_sse_block(lines) == KEEPALIVE
    del learner


async def test_learner_stream_requires_token(
    stream_settings: Settings,
    pg_engine: AsyncEngine,
    db: SessionFactory,
    pg_db: Db,
    neo4j: AsyncDriver,
    redis: Redis,
) -> None:
    resources = build_app_resources(
        stream_settings, pg_engine, neo4j, redis, db=pg_db, session_factory=db
    )
    async with _client(create_app(stream_settings, resources=resources)) as client:
        response = await client.get("/v1/learner/stream")
    assert response.status_code == 401


async def _p4_change(pg_db: Db, learner: UUID, redis: Redis | None, type_: str) -> UUID:
    """One §4.8 change event in the Phase 4 log; returns the id the message names."""
    object_id = uuid4()
    payload: dict[str, Any] = (
        {"material_id": str(object_id), "pages_count": 3}
        if type_ == "material.parsed"
        else {
            "artifact_id": str(object_id),
            "version": 1,
            "kind": "notes",
            "topic_id": str(uuid4()),
            "text": "notes",
        }
    )
    await p4_append(
        pg_db,
        learner,
        [P4Event(type=type_, payload=payload, actor="code", idempotency_key=str(uuid4()))],
        redis=redis,
    )
    return object_id


async def test_learner_stream_reports_artifacts_and_materials(
    stream_settings: Settings,
    pg_engine: AsyncEngine,
    db: SessionFactory,
    pg_db: Db,
    neo4j: AsyncDriver,
    redis: Redis,
) -> None:
    """ТЗ Ф4 §4.8 (Redis): `material.parsed` / `artifact.updated` written after the stream
    opened → `material_parsed {material_id}` / `artifact_updated {artifact_id}` on the signal
    `learner:{id}`; events before the stream are not repeated."""
    learner = await create_learner(pg_db)
    await ensure_user(db, learner)
    headers = session_cookie(await session_token(pg_db, learner, stream_settings))
    await _p4_change(pg_db, learner, None, "material.parsed")  # before the stream
    resources = build_app_resources(
        stream_settings, pg_engine, neo4j, redis, db=pg_db, session_factory=db
    )
    app = create_app(stream_settings, resources=resources)
    async with (
        _client(app) as client,
        client.stream("GET", "/v1/learner/stream", headers=headers) as r,
    ):
        lines = r.aiter_lines()
        assert (await next_sse_event(lines))[0] == "projection_advanced"
        await _wait_subscribers(redis, learner_signal_channel(learner), 1)
        material = await _p4_change(pg_db, learner, redis, "material.parsed")
        assert await next_sse_event(lines) == ("material_parsed", {"material_id": str(material)})
        artifact = await _p4_change(pg_db, learner, redis, "artifact.updated")
        assert await next_sse_event(lines) == ("artifact_updated", {"artifact_id": str(artifact)})


async def test_learner_stream_reports_changes_without_redis(
    stream_settings: Settings,
    pg_engine: AsyncEngine,
    db: SessionFactory,
    pg_db: Db,
    neo4j: AsyncDriver,
) -> None:
    """ТЗ Ф4 §4.8 (broken Redis): the change events arrive by polling."""
    learner = await create_learner(pg_db)
    await ensure_user(db, learner)
    headers = session_cookie(await session_token(pg_db, learner, stream_settings))
    resources = build_app_resources(
        stream_settings, pg_engine, neo4j, BrokenRedis(), db=pg_db, session_factory=db
    )
    app = create_app(stream_settings, resources=resources)
    async with (
        _client(app) as client,
        client.stream("GET", "/v1/learner/stream", headers=headers) as r,
    ):
        lines = r.aiter_lines()
        assert (await next_sse_event(lines))[0] == "projection_advanced"
        artifact = await _p4_change(pg_db, learner, None, "artifact.updated")
        assert await next_sse_event(lines) == ("artifact_updated", {"artifact_id": str(artifact)})


async def test_learner_stream_reports_revised_verdicts(
    stream_settings: Settings,
    pg_engine: AsyncEngine,
    db: SessionFactory,
    pg_db: Db,
    neo4j: AsyncDriver,
) -> None:
    """ТЗ Ф4 §4.8, `Т-§5.6`, D-B-167: `task.key_disputed {task_id}` → `verdict_revised
    {answer_seq}` for each answer of the task that already has a verdict, not for the rest."""
    learner = await create_learner(pg_db)
    await ensure_user(db, learner)
    headers = session_cookie(await session_token(pg_db, learner, stream_settings))
    task_id = uuid4()

    def event(type_: str, payload: dict[str, Any]) -> P4Event:
        return P4Event(type=type_, payload=payload, actor="code", idempotency_key=str(uuid4()))

    answer = {"task_id": str(task_id), "answer": {"kind": "number", "value": "2"}, "source": "chat"}
    judged, unjudged = await p4_append(
        pg_db,
        learner,
        [event("answer.submitted", answer), event("answer.submitted", answer)],
    )
    verdict = {"part": "main", "outcome": "correct", "method": "exact", "verification": "code"}
    await p4_append(
        pg_db, learner, [event("verdict.recorded", {"answer_seq": judged.seq, **verdict})]
    )
    resources = build_app_resources(
        stream_settings, pg_engine, neo4j, BrokenRedis(), db=pg_db, session_factory=db
    )
    app = create_app(stream_settings, resources=resources)
    async with (
        _client(app) as client,
        client.stream("GET", "/v1/learner/stream", headers=headers) as r,
    ):
        lines = r.aiter_lines()
        assert (await next_sse_event(lines))[0] == "projection_advanced"
        await p4_append(pg_db, learner, [event("task.key_disputed", {"task_id": str(task_id)})])
        assert await next_sse_event(lines) == ("verdict_revised", {"answer_seq": judged.seq})
        with pytest.raises(TimeoutError):  # the answer without a verdict is not revised
            await next_sse_event(lines, timeout_s=0.3)
    assert unjudged.seq != judged.seq
