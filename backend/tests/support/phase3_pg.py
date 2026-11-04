"""Postgres of Phases 1-3 for the tests that still run on it (ТЗ Ф4 WP1.3, step 5).

The Alembic database and its SQLAlchemy engine are what the tests of streams A and B that still
test Phase 3 code (`test_learner_stream`, `test_worker_and_ops`, `jobs`, `domains`, `session`)
use through the fixtures `pg_engine` and `db` and through `ensure_user`. No test of stream C
requests them: zone C runs on `pg_db` of `tests/db/fixtures.py`. The module goes away together
with the last of those tests (step 5 of WP1.3, T-DB3); it is registered in `tests/conftest.py`
(`pytest_plugins`) so that no other file imports SQLAlchemy.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from uuid import UUID

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from quack.config import Settings
from quack.db.postgres import SessionFactory, create_engine, create_session_factory
from tests.conftest import BACKEND_DIR, _unavailable

ALL_TABLES = (
    "auth.users",
    "core.learner_seq",
    "core.events",
    "core.sessions",
    "core.artifacts",
    "core.domains",
    "core.task_bank",
    "core.llm_outbox",
    "ops.jobs",
    "ops.dlq",
    "ops.llm_ledger",
    "ops.deletion_tombstones",
    "ops.projector_offsets",
    "ops.event_types_seen",
    "ops.dispatcher_offsets",
    "ops.turn_manifests",
)

_INSERT_USER = text(
    "INSERT INTO auth.users (id, email, password_hash, display_name) "
    "VALUES (:id, :email, 'test-only', 'Test learner') ON CONFLICT (id) DO NOTHING"
)


def _migrate(dsn: str) -> None:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    cfg.set_main_option("sqlalchemy.url", dsn)
    command.upgrade(cfg, "head")


@pytest.fixture(scope="session")
async def pg_engine(settings: Settings) -> AsyncIterator[AsyncEngine]:
    engine = create_engine(settings, pool_size=5)
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception as exc:  # pragma: no cover - depends on environment
        await engine.dispose()
        _unavailable("Postgres", exc)
    async with engine.begin() as conn:
        for schema in ("ops", "core", "auth"):
            await conn.execute(text(f"DROP SCHEMA IF EXISTS {schema} CASCADE"))
        await conn.execute(text("DROP TABLE IF EXISTS public.alembic_version"))
    await asyncio.to_thread(_migrate, settings.sqlalchemy_dsn)
    yield engine
    await engine.dispose()


@pytest.fixture
async def db(pg_engine: AsyncEngine) -> SessionFactory:
    async with pg_engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE {', '.join(ALL_TABLES)}"))
    return create_session_factory(pg_engine)


async def ensure_user(db: SessionFactory, learner_id: UUID) -> None:
    """The Phase 3 account row of `learner_id` (no-op when it exists): the Phase 3 log
    (`core.events`) holds a foreign key to it."""
    async with db() as session, session.begin():
        await session.execute(
            _INSERT_USER, {"id": learner_id, "email": f"{learner_id}@test.invalid"}
        )
