"""`ops db-roles`: the three Postgres roles of Д-§7 / Т-§19.8 (ТЗ Фазы 4 WP9.6).

- `quack_migrator` owns the schemas and runs DDL (migrations);
- `quack_app` reads and writes the tables of the application schemas, no DDL;
- `quack_reader` is a member of `pg_read_all_data` (dump, alert checks).

Idempotent: runs on the first start, at every rollout and before `pg_restore` (`pg_dump` does not
save roles, Д-§7). Connect as the database superuser. Passwords are set on every run, so a rotation
is a new value plus a rollout. Objects created later by `quack_migrator` get the grants through
default privileges, so the command may run before the first migration.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from quack.config import Settings
from quack.logging import get_logger

log = get_logger(__name__)

MIGRATOR = "quack_migrator"
APP = "quack_app"
READER = "quack_reader"

# Д-§7 names `core`, `content`, `ops`; `auth` (users, sessions) is used by the API as well.
# TODO(owner): confirm that `auth` belongs to the application schemas of `quack_app`.
APP_SCHEMAS = ("auth", "core", "content", "ops")


class DbRolesRefused(Exception):
    """A password is missing: a role without one could not be used."""


@dataclass(frozen=True)
class RolePasswords:
    migrator: str
    app: str
    reader: str

    @classmethod
    def from_settings(cls, settings: Settings) -> RolePasswords:
        values = {
            "MIGRATOR_DB_PASSWORD": settings.migrator_db_password.get_secret_value(),
            "APP_DB_PASSWORD": settings.app_db_password.get_secret_value(),
            "READER_DB_PASSWORD": settings.reader_db_password.get_secret_value(),
        }
        missing = [name for name, value in values.items() if not value]
        if missing:
            raise DbRolesRefused(f"set {', '.join(missing)}")
        return cls(
            migrator=values["MIGRATOR_DB_PASSWORD"],
            app=values["APP_DB_PASSWORD"],
            reader=values["READER_DB_PASSWORD"],
        )


async def _exec(conn: AsyncConnection, sql: str) -> None:
    await conn.exec_driver_sql(sql)


async def _ensure_role(conn: AsyncConnection, role: str, password: str) -> None:
    exists = (
        await conn.execute(text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": role})
    ).first()
    verb = "ALTER" if exists else "CREATE"
    # `%I` and `%L` quote on the server: a password cannot be a bind parameter in this statement.
    statement = (
        await conn.execute(
            text("SELECT format(:tpl, CAST(:r AS text), CAST(:p AS text))"),
            {
                "tpl": f"{verb} ROLE %I LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD %L",
                "r": role,
                "p": password,
            },
        )
    ).scalar_one()
    # Raw driver SQL (asyncpg): no parameter marks inside, so `%` and `:` in a password stay as is.
    await _exec(conn, str(statement))


async def _existing_schemas(conn: AsyncConnection) -> list[str]:
    rows = await conn.execute(
        text("SELECT nspname FROM pg_namespace WHERE nspname = ANY(:names)"),
        {"names": list(APP_SCHEMAS)},
    )
    return sorted(row[0] for row in rows)


async def apply_db_roles(engine: AsyncEngine, passwords: RolePasswords) -> list[str]:
    """Create or update the roles and grants; returns the application schemas that were found."""
    async with engine.begin() as conn:
        database = (await conn.execute(text("SELECT current_database()"))).scalar_one()
        await _ensure_role(conn, MIGRATOR, passwords.migrator)
        await _ensure_role(conn, APP, passwords.app)
        await _ensure_role(conn, READER, passwords.reader)
        await _exec(conn, f'GRANT CREATE, CONNECT ON DATABASE "{database}" TO {MIGRATOR}')
        await _exec(conn, f'GRANT CONNECT ON DATABASE "{database}" TO {APP}, {READER}')
        await _exec(conn, f"GRANT pg_read_all_data TO {READER}")
        # What `quack_migrator` creates from now on (Д-§7: it owns the schemas and the tables).
        for grantee in (APP, READER):
            await _exec(
                conn,
                f"ALTER DEFAULT PRIVILEGES FOR ROLE {MIGRATOR} GRANT USAGE ON SCHEMAS TO {grantee}",
            )
        await _exec(
            conn,
            f"ALTER DEFAULT PRIVILEGES FOR ROLE {MIGRATOR} "
            f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {APP}",
        )
        await _exec(
            conn,
            f"ALTER DEFAULT PRIVILEGES FOR ROLE {MIGRATOR} "
            f"GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO {APP}",
        )
        # What exists already (the superuser created it before the roles did).
        schemas = await _existing_schemas(conn)
        for schema in schemas:
            await _exec(conn, f"ALTER SCHEMA {schema} OWNER TO {MIGRATOR}")
            relations = await conn.execute(
                text(
                    "SELECT c.relkind, c.relname FROM pg_class c "
                    "JOIN pg_namespace n ON n.oid = c.relnamespace "
                    "WHERE n.nspname = :s AND c.relkind IN ('r', 'p', 'S', 'v', 'm') "
                    # A sequence of a serial or identity column follows its table's owner.
                    "AND NOT (c.relkind = 'S' AND EXISTS (SELECT 1 FROM pg_depend d "
                    "WHERE d.objid = c.oid AND d.deptype IN ('a', 'i')))"
                ),
                {"s": schema},
            )
            for kind, name in relations.all():
                what = "SEQUENCE" if kind == "S" else "TABLE"
                await _exec(conn, f'ALTER {what} {schema}."{name}" OWNER TO {MIGRATOR}')
            await _exec(conn, f"GRANT USAGE ON SCHEMA {schema} TO {APP}, {READER}")
            await _exec(
                conn,
                f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA {schema} TO {APP}",
            )
            await _exec(
                conn,
                f"GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA {schema} TO {APP}",
            )
    log.info("db_roles_applied", schemas=schemas)
    return schemas
