"""Process resources and handler registration of `workers` / `projector` (ТЗ Фазы 3 §4.2, WP2).

Resources are built once per process and passed explicitly; they are closed in reverse order.
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass

from neo4j import AsyncDriver
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine

from quack.compute_client.client import create_compute_client
from quack.config import Settings
from quack.db import open_db
from quack.db.neo4j import create_driver
from quack.db.postgres import SessionFactory, create_engine, create_session_factory
from quack.db.redis import create_redis
from quack.embeddings.client import create_embedding_client
from quack.jobs.kinds import JOB_KINDS
from quack.jobs.runner import JOB_HANDLERS, JobContext, JobHandler
from quack.llm.gateway import LLMGateway
from quack.llm.responses_client import ResponsesClient
from quack.storage.deletions import create_deletion_journal
from quack.storage.objects import create_object_store

# WP2.2: modules that hold `@register_job_handler` (kind -> module is checked by T-Q7).
HANDLER_MODULES: tuple[str, ...] = (
    "quack.domains.curation",
    "quack.session.lifecycle",
    "quack.session.workers",
    "quack.artifacts.cheatsheets",
    "quack.ops.purge_job",
    "quack.artifacts.topic_refresh",
    "quack.agents.viz",
    "quack.canvas.photo_pipeline",
)


async def create_job_context(settings: Settings) -> JobContext:
    """Build the resources of ТЗ Ф4 §4.2 once per process, in creation order (WP2.1)."""
    db = await open_db(settings)
    engine = create_engine(settings)
    session_factory = create_session_factory(engine)
    neo4j = create_driver(settings)
    redis = create_redis(settings)
    provider = ResponsesClient(settings.meta_api_base_url, settings.meta_api_key.get_secret_value())
    return JobContext(
        settings=settings,
        db=db,
        session_factory=session_factory,
        engine=engine,
        neo4j=neo4j,
        redis=redis,
        llm=LLMGateway(session_factory, provider, settings),
        compute=create_compute_client(settings),
        storage=create_object_store(settings),
        embeddings=create_embedding_client(settings),
        deletions=create_deletion_journal(settings),
    )


async def close_job_context(context: JobContext) -> None:
    """Close in reverse creation order: deletions, embeddings, storage, compute, llm, redis,
    neo4j, engine, db (§4.2)."""
    await context.deletions.aclose()
    await context.embeddings.aclose()
    await context.storage.aclose()
    await context.compute.aclose()
    await context.llm.aclose()
    if context.redis is not None:
        await context.redis.aclose()
    await context.neo4j.close()
    await context.engine.dispose()
    await context.db.close()


@dataclass(frozen=True)
class ProjectorContext:
    """Resources of the `projector` process (§4.2): no LLM gateway, no compute client."""

    settings: Settings
    session_factory: SessionFactory
    engine: AsyncEngine
    neo4j: AsyncDriver
    redis: Redis | None


def create_projector_context(settings: Settings) -> ProjectorContext:
    engine = create_engine(settings)
    return ProjectorContext(
        settings=settings,
        session_factory=create_session_factory(engine),
        engine=engine,
        neo4j=create_driver(settings),
        redis=create_redis(settings),
    )


async def close_projector_context(context: ProjectorContext) -> None:
    """Reverse creation order: redis, neo4j, engine."""
    if context.redis is not None:
        await context.redis.aclose()
    await context.neo4j.close()
    await context.engine.dispose()


def register_all_handlers() -> dict[str, JobHandler]:
    """Import every product module with `@register_job_handler`; return the registry (WP2.2)."""
    for module in HANDLER_MODULES:
        importlib.import_module(module)
    return dict(JOB_HANDLERS)


class JobHandlersMismatchError(RuntimeError):
    """`job_handlers_mismatch`: registered handlers differ from `JOB_KINDS` (T-Q7)."""

    def __init__(self, missing: list[str], extra: list[str]) -> None:
        super().__init__(f"job_handlers_mismatch: missing={missing} extra={extra}")
        self.missing = missing
        self.extra = extra


def check_handlers_complete(handlers: dict[str, JobHandler]) -> None:
    """Raise `JobHandlersMismatchError` unless `handlers` keys equal `JOB_KINDS` (WP2.2)."""
    missing = sorted(set(JOB_KINDS) - set(handlers))
    extra = sorted(set(handlers) - set(JOB_KINDS))
    if missing or extra:
        raise JobHandlersMismatchError(missing, extra)
