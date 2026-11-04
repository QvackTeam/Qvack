"""Builders of process resources with test dependencies (ТЗ Фазы 3 §4.2, §8.1, seam S1).

ТЗ Фазы 4 §4.2: `AppResources` also gets `storage`, `embeddings`, `email`, `deletions`; by default
they are the in-memory doubles of `tests.support` (§8.1). WP1.3: `AppResources` has no SQLAlchemy
pair and the gateway runs on `Db` only (D-B-212), so the builders take the pools `neo4j` and
`redis` and the `Db` of the test (`pg_db`), nothing else.

Until the tests of streams A and B that still call the builders with the Phase 3 arguments leave
(step 5 of WP1.3), the builders accept those as extra arguments and drop them: a leading pool in
front of `neo4j` and keywords that name a retired argument (`_RETIRED_NOTE`). Zone C passes none.

`build_app_resources` assembles `quack.api.resources.AppResources` from the test pools,
`build_job_context` assembles `quack.jobs.runner.JobContext` (WP2.1, conflict 20 of §2.3).
"""

from __future__ import annotations

import dataclasses
from typing import Any, cast

from neo4j import AsyncDriver
from psycopg_pool import AsyncConnectionPool
from redis.asyncio import Redis

from quack.api.email import EmailSender
from quack.api.resources import AppResources
from quack.compute_client.client import ComputeClient
from quack.config import Settings
from quack.db import Db
from quack.embeddings.client import EmbeddingClient
from quack.jobs.runner import JobContext
from quack.llm.gateway import LLMGateway
from quack.llm.provider import LLMProvider
from quack.storage.deletions import DeletionJournal
from quack.storage.objects import ObjectStore
from tests.support.compute import ComputeScenario, scripted_compute
from tests.support.deletions import FakeDeletionJournal
from tests.support.email import FakeEmailSender
from tests.support.embeddings import FakeEmbeddingClient
from tests.support.llm import UnavailableLLMProvider
from tests.support.storage import InMemoryObjectStore

_RETIRED_NOTE = "arguments of the Phase 3 stack, accepted and dropped until streams A and B move"

# The fields of `JobContext` this module fills; the rest are retired fields of Phase 3 that
# `quack.jobs.runner` drops with its Phase 3 handlers (step 5), then they are not built here.
_CONTEXT_FIELDS = frozenset(
    {"settings", "db", "neo4j", "redis", "llm", "compute", "storage", "embeddings", "deletions"}
)


def _pools(pools: tuple[Any, ...]) -> tuple[tuple[Any, ...], Any, Any]:
    """`(leading retired pools, neo4j, redis)`: the call is `(neo4j, redis)` or, in the Phase 3
    shape, `(<pool>, neo4j, redis)`."""
    if len(pools) not in (2, 3):
        raise TypeError(f"expected `neo4j, redis` after settings, got {len(pools)} pools")
    return pools[:-2], pools[-2], pools[-1]


def build_app_resources(
    settings: Settings,
    *pools: Any,
    db: Db | None = None,
    provider: LLMProvider | None = None,
    compute: ComputeClient | None = None,
    storage: ObjectStore | None = None,
    embeddings: EmbeddingClient | None = None,
    email: EmailSender | None = None,
    deletions: DeletionJournal | None = None,
    **retired: Any,
) -> AppResources:
    """`AppResources` over the test pools: `build_app_resources(settings, neo4j, redis, db=pg_db)`.
    `neo4j` / `redis` may be the broken doubles of `tests.support.broken`; by default the LLM is
    down (`UnavailableLLMProvider`) and compute is an empty `ComputeScenario` (answers 503);
    storage, embeddings, email and the deletion journal are the working in-memory doubles. Without
    `db` (pass `pg_db`, seam S2) the `Db` is over a closed pool: a test that touches Postgres
    through it fails with `PoolClosed`. `retired`: see `_RETIRED_NOTE`."""
    _, neo4j, redis = _pools(pools)
    db = db or Db(AsyncConnectionPool(settings.postgres_dsn, open=False))
    return AppResources(
        settings=settings,
        db=db,
        neo4j=cast(AsyncDriver, neo4j),
        redis=cast(Redis | None, redis),
        llm=LLMGateway(provider or UnavailableLLMProvider(), settings, db=db),
        compute=compute or scripted_compute(ComputeScenario()),
        storage=storage or InMemoryObjectStore(),
        embeddings=embeddings or FakeEmbeddingClient(settings.embedding_dim),
        email=email or FakeEmailSender(),
        deletions=deletions or FakeDeletionJournal(),
    )


def build_job_context(
    settings: Settings,
    *pools: Any,
    db: Db | None = None,
    llm: LLMGateway | None = None,
    provider: LLMProvider | None = None,
    compute: ComputeClient | None = None,
    storage: ObjectStore | None = None,
    embeddings: EmbeddingClient | None = None,
    deletions: DeletionJournal | None = None,
    **retired: Any,
) -> JobContext:
    """`JobContext` over the test pools: `build_job_context(settings, neo4j, redis, db=pg_db)`.
    `llm` is used as is (e.g. `FakeLLMProvider.gateway`); otherwise a gateway over `provider`, by
    default the LLM is down (`UnavailableLLMProvider`). Compute defaults to an empty
    `ComputeScenario` (answers 503); storage, embeddings and the deletion journal are the in-memory
    doubles. Without `db` (pass `pg_db`, seam S2) the `Db` is over a closed pool, as in
    `build_app_resources`. The retired fields of `JobContext` are filled from `retired`
    (`_RETIRED_NOTE`), else with `None`."""
    leading, neo4j, redis = _pools(pools)
    db = db or Db(AsyncConnectionPool(settings.postgres_dsn, open=False))
    retired_fields = [
        f.name for f in dataclasses.fields(JobContext) if f.name not in _CONTEXT_FIELDS
    ]
    legacy = dict(zip(retired_fields, leading, strict=False)) | retired
    return JobContext(
        settings=settings,
        db=db,
        neo4j=cast(AsyncDriver, neo4j),
        redis=cast(Redis | None, redis),
        llm=llm or LLMGateway(provider or UnavailableLLMProvider(), settings, db=db),
        compute=compute or scripted_compute(ComputeScenario()),
        storage=storage or InMemoryObjectStore(),
        embeddings=embeddings or FakeEmbeddingClient(settings.embedding_dim),
        deletions=deletions or FakeDeletionJournal(),
        **{name: legacy.get(name) for name in retired_fields},
    )
