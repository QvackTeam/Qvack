"""Handler of `account.purge_deleted` (ТЗ Фазы 3 WP3.3), in the assembly layer because it calls
`ops purge-deleted` (§4.1).

Stream A removes this module with the Phase 3 runtime (ТЗ Ф4 WP1.3 step 5, `REMOVED_JOB_KINDS`).
The body of `purge_deleted` moved here from `quack.ops.commands` (D-C-180): the command itself is
gone from the CLI, only this handler still calls it, and `commands` has no SQLAlchemy any more.
"""

from __future__ import annotations

from uuid import UUID

from neo4j import AsyncDriver
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from quack.db.locks import LockKeyspace, advisory_lock
from quack.db.postgres import SessionFactory
from quack.db.redis import presence_key, ratelimit_key
from quack.graph.neo4j_store import Neo4jGraphStore
from quack.jobs.queue import ClaimedJob
from quack.jobs.runner import JobContext, register_job_handler
from quack.logging import get_logger

log = get_logger(__name__)

# Tables with learner data removed by purge-deleted (Т-§2.9, Т-§16.3).
PURGE_TABLES = (
    "core.events",
    "core.learner_seq",
    "core.sessions",
    "core.artifacts",
    "core.domains",
    "core.task_bank",
    "core.llm_outbox",
    "ops.llm_ledger",
    "ops.jobs",
    "ops.dlq",
    "ops.projector_offsets",
    "ops.dispatcher_offsets",
    "ops.turn_manifests",
)


async def _delete_redis_keys(redis: Redis, learner_id: UUID) -> None:
    keys = [presence_key(learner_id)]
    keys.extend([key async for key in redis.scan_iter(match=ratelimit_key("*", str(learner_id)))])
    await redis.delete(*keys)


async def purge_deleted(
    engine: AsyncEngine,
    session_factory: SessionFactory,
    driver: AsyncDriver,
    *,
    chunk_size: int,
    redis: Redis | None = None,
) -> list[UUID]:
    """Physically delete learners with a pending_purge tombstone (Т-§2.9); with `redis`, also
    their keys `presence:learner:{id}` and `ratelimit:*:{id}` (Т-§19.5)."""
    async with session_factory() as session:
        pending = [
            row[0]
            for row in await session.execute(
                text(
                    "SELECT learner_id FROM ops.deletion_tombstones "
                    "WHERE status = 'pending_purge' ORDER BY requested_at"
                )
            )
        ]
    purged: list[UUID] = []
    for learner_id in pending:
        async with advisory_lock(engine, LockKeyspace.LEARNER_PROJECTION, learner_id) as ok:
            if not ok:
                log.info("purge_skipped_locked", learner_id=str(learner_id))
                continue
            async with session_factory() as session, session.begin():
                for table in PURGE_TABLES:
                    await session.execute(
                        text(f"DELETE FROM {table} WHERE learner_id = :l"), {"l": learner_id}
                    )
                await session.execute(
                    text("DELETE FROM auth.users WHERE id = :l"), {"l": learner_id}
                )
            await Neo4jGraphStore(driver, str(learner_id)).delete_learner(chunk_size=chunk_size)
            if redis is not None:
                await _delete_redis_keys(redis, learner_id)
            async with session_factory() as session, session.begin():
                await session.execute(
                    text(
                        "UPDATE ops.deletion_tombstones SET status = 'purged', purged_at = now() "
                        "WHERE learner_id = :l"
                    ),
                    {"l": learner_id},
                )
            purged.append(learner_id)
            log.info("learner_purged", learner_id=str(learner_id))
    return purged


@register_job_handler("account.purge_deleted")
async def handle_purge_deleted(job: ClaimedJob, ctx: JobContext) -> None:
    """The logic of `ops purge-deleted` over the resources of `ctx`, plus the Redis keys of the
    learner (`presence:learner:{id}`, `ratelimit:*:{id}`; Т-§19.5)."""
    await purge_deleted(
        ctx.engine,
        ctx.session_factory,
        ctx.neo4j,
        chunk_size=ctx.settings.rebuild_max_tx_ops,
        redis=ctx.redis,
    )
