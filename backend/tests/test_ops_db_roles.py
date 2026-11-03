"""T-OPS2 (ТЗ Фазы 4): `ops db-roles` is idempotent; `quack_app` has no DDL; reader reads."""

from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.engine import URL
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from quack.config import Settings
from quack.ops.db_roles import (
    APP,
    MIGRATOR,
    READER,
    DbRolesRefused,
    RolePasswords,
    apply_db_roles,
)

PASSWORDS = RolePasswords(migrator="m-pass'1%x", app='a-pass"2', reader="r-pass;3")


@pytest.fixture
async def scratch(pg_engine: AsyncEngine) -> AsyncIterator[URL]:
    """A throwaway database: the roles are cluster-wide, the shared test schema stays untouched."""
    name = f"quack_roles_{uuid4().hex[:8]}"
    admin = create_async_engine(pg_engine.url, isolation_level="AUTOCOMMIT")
    async with admin.connect() as conn:
        await conn.execute(text(f'CREATE DATABASE "{name}"'))
    url = pg_engine.url.set(database=name)
    owner = create_async_engine(url)
    async with owner.begin() as conn:
        for schema in ("auth", "core", "content", "ops"):
            await conn.execute(text(f"CREATE SCHEMA {schema}"))
        await conn.execute(text("CREATE TABLE core.events (id serial PRIMARY KEY, body text)"))
        await conn.execute(text("CREATE TABLE ops.jobs (id serial PRIMARY KEY, kind text)"))
    await owner.dispose()
    try:
        yield url
    finally:
        async with admin.connect() as conn:
            await conn.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))
        await admin.dispose()


def as_role(url: URL, role: str, password: str) -> AsyncEngine:
    return create_async_engine(url.set(username=role, password=password))


async def test_roles_are_applied_twice_without_error(scratch: URL):
    engine = create_async_engine(scratch)
    try:
        first = await apply_db_roles(engine, PASSWORDS)
        second = await apply_db_roles(engine, PASSWORDS)
    finally:
        await engine.dispose()

    assert first == second == ["auth", "content", "core", "ops"]


async def test_app_reads_and_writes_but_has_no_ddl(scratch: URL):
    engine = create_async_engine(scratch)
    try:
        await apply_db_roles(engine, PASSWORDS)
    finally:
        await engine.dispose()

    app = as_role(scratch, APP, PASSWORDS.app)
    try:
        async with app.begin() as conn:
            await conn.execute(text("INSERT INTO core.events (body) VALUES ('x')"))
            await conn.execute(text("UPDATE core.events SET body = 'y'"))
            assert (await conn.execute(text("SELECT count(*) FROM ops.jobs"))).scalar_one() == 0
        for ddl in (
            "CREATE TABLE core.sneaky (id int)",
            "DROP TABLE core.events",
            "ALTER TABLE core.events ADD COLUMN extra int",
            "CREATE SCHEMA sneaky",
        ):
            with pytest.raises(DBAPIError, match=r"permission denied|must be owner"):
                async with app.begin() as conn:
                    await conn.execute(text(ddl))
    finally:
        await app.dispose()


async def test_reader_only_reads(scratch: URL):
    engine = create_async_engine(scratch)
    try:
        await apply_db_roles(engine, PASSWORDS)
        async with engine.begin() as conn:
            await conn.execute(text("INSERT INTO core.events (body) VALUES ('x')"))
    finally:
        await engine.dispose()

    reader = as_role(scratch, READER, PASSWORDS.reader)
    try:
        async with reader.begin() as conn:
            assert (await conn.execute(text("SELECT count(*) FROM core.events"))).scalar_one() == 1
        with pytest.raises(DBAPIError, match="permission denied"):
            async with reader.begin() as conn:
                await conn.execute(text("INSERT INTO core.events (body) VALUES ('y')"))
    finally:
        await reader.dispose()


async def test_tables_created_later_by_the_migrator_reach_the_app(scratch: URL):
    engine = create_async_engine(scratch)
    try:
        await apply_db_roles(engine, PASSWORDS)
    finally:
        await engine.dispose()

    migrator = as_role(scratch, MIGRATOR, PASSWORDS.migrator)
    app = as_role(scratch, APP, PASSWORDS.app)
    try:
        async with migrator.begin() as conn:
            await conn.execute(text("CREATE SCHEMA fresh"))
            await conn.execute(text("CREATE TABLE core.later (id serial PRIMARY KEY, v int)"))
        async with app.begin() as conn:
            await conn.execute(text("INSERT INTO core.later (v) VALUES (1)"))
    finally:
        await migrator.dispose()
        await app.dispose()


async def test_a_second_run_rotates_the_password(scratch: URL):
    engine = create_async_engine(scratch)
    rotated = RolePasswords(migrator="m2", app="a2", reader="r2")
    try:
        await apply_db_roles(engine, PASSWORDS)
        await apply_db_roles(engine, rotated)
    finally:
        await engine.dispose()

    app = as_role(scratch, APP, "a2")
    try:
        async with app.connect() as conn:
            assert (await conn.execute(text("SELECT current_user"))).scalar_one() == APP
    finally:
        await app.dispose()


def test_missing_passwords_are_refused():
    settings = Settings(_env_file=None, app_db_password=SecretStr("only-app"))  # type: ignore[call-arg]

    with pytest.raises(DbRolesRefused, match="MIGRATOR_DB_PASSWORD") as info:
        RolePasswords.from_settings(settings)
    assert "APP_DB_PASSWORD" not in str(info.value)
