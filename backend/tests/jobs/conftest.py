"""Postgres of Phase 4 for the queue and the dispatcher (ТЗ Ф4 WP7, §8.5).

A private database `<test db>_p4_wp7` is created from `db/migrations/*.sql` straight through
psycopg (the `migrate:up` part of each file, in file order), so these tests need no `dbmate`
and do not share a database with the tests that truncate `<test db>_p4`. Tables are emptied
before each test.
"""

from __future__ import annotations

import asyncio
import sys
from collections.abc import AsyncIterator
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg import sql
from sqlalchemy import text

from quack.config import Settings
from quack.db import Db, open_db
from quack.db.postgres import SessionFactory
from quack.events.append import append_events
from quack.events.models import NewEvent
from tests.conftest import PG_DSN, _unavailable
from tests.db.fixtures import MIGRATIONS_DIR, PHASE4_SCHEMAS, database_url
from tests.support.auth import session_token

if sys.platform == "win32":  # psycopg cannot run on the default ProactorEventLoop
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())  # type: ignore[attr-defined,deprecated]

WP7_DATABASE = urlsplit(PG_DSN).path.lstrip("/") + "_p4_wp7"


def _up_part(text: str) -> str:
    up = text.split("-- migrate:up", 1)[1].split("-- migrate:down", 1)[0]
    return up.split("\n", 1)[1]  # the rest of the marker line (`transaction:false`)


async def _recreate_database() -> None:
    admin = database_url(urlsplit(PG_DSN).path.lstrip("/"))
    async with await psycopg.AsyncConnection.connect(admin, autocommit=True) as conn:
        name = sql.Identifier(WP7_DATABASE)
        await conn.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(name))
        await conn.execute(sql.SQL("CREATE DATABASE {}").format(name))
    async with await psycopg.AsyncConnection.connect(
        database_url(WP7_DATABASE), autocommit=True
    ) as conn:
        for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
            await conn.execute(_up_part(path.read_text(encoding="utf-8")))  # type: ignore[arg-type]


@pytest.fixture(scope="session")
async def wp7_db_session(settings: Settings) -> AsyncIterator[Db]:
    try:
        await _recreate_database()
    except Exception as exc:
        _unavailable("Postgres for the WP7 tests", exc)
    db = await open_db(settings.model_copy(update={"postgres_dsn": database_url(WP7_DATABASE)}))
    try:
        yield db
    finally:
        await db.close()


@pytest.fixture
async def jobs_db(wp7_db_session: Db) -> Db:
    """`Db` over the private database with every table of core/content/ops emptied."""
    rows = await wp7_db_session.fetch_all(
        "SELECT table_schema, table_name FROM information_schema.tables "
        "WHERE table_schema = ANY(%(schemas)s) AND table_type = 'BASE TABLE'",
        {"schemas": list(PHASE4_SCHEMAS)},
    )
    tables = sql.SQL(", ").join(sql.Identifier(r["table_schema"], r["table_name"]) for r in rows)
    await wp7_db_session.execute(sql.SQL("TRUNCATE {} RESTART IDENTITY").format(tables))
    return wp7_db_session


@pytest.fixture
async def seeded_learner(db: SessionFactory, pg_db: Db, settings: Settings) -> tuple[UUID, str]:
    """A learner of the Phase 3 log (`auth.users` + `learner.registered`)."""
    learner_id = uuid4()
    email = f"learner-{learner_id.hex[:8]}@example.com"
    async with db() as session, session.begin():
        await session.execute(
            text(
                "INSERT INTO auth.users (id, email, password_hash, display_name, preferences) "
                "VALUES (:id, :email, :pw, :name, CAST(:prefs AS JSONB))"
            ),
            {"id": learner_id, "email": email, "pw": "!", "name": "Seeded", "prefs": "{}"},
        )
        await append_events(
            session,
            learner_id,
            [
                NewEvent(
                    type="learner.registered",
                    actor="learner",
                    idempotency_key=f"register:{learner_id}",
                    payload={"email": email, "display_name": "Seeded", "preferences": {}},
                )
            ],
            publish_wakeup=False,
        )
    return learner_id, await session_token(pg_db, learner_id, settings)
