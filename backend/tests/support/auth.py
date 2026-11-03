"""Auth helpers of the tests (ТЗ Фазы 3 WP1.2, D-C-004; ТЗ Ф4 WP18.3, D-C-112).

The single auth dependency accepts a token only for an existing `auth.users` row. Phase 2
session tests mint tokens for random learner ids; `ensure_users_hook` gives every such id a
user row before the request is sent, as registration would. A row that already exists (for
example one with `deleted_at` set) is left as it is.

Routes on Phase 4 sessions sign in with `login`: a `core.auth_sessions` row and the cookie on
the client (D-C-112 п.2).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from uuid import UUID

import httpx
import jwt
from sqlalchemy import text

from quack.api.auth import SESSION_COOKIE
from quack.auth.sessions import open_session
from quack.config import Settings
from quack.db import Db
from quack.db.postgres import SessionFactory

type RequestHook = Callable[[httpx.Request], Awaitable[None]]

_INSERT_USER = text(
    "INSERT INTO auth.users (id, email, password_hash, display_name) "
    "VALUES (:id, :email, 'test-only', 'Test learner') ON CONFLICT (id) DO NOTHING"
)


async def ensure_user(db: SessionFactory, learner_id: UUID) -> None:
    """An active `auth.users` row for `learner_id` (no-op when the row exists)."""
    async with db() as session, session.begin():
        await session.execute(
            _INSERT_USER, {"id": learner_id, "email": f"{learner_id}@test.invalid"}
        )


def _bearer_subject(request: httpx.Request) -> UUID | None:
    scheme, _, token = request.headers.get("Authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    try:
        claims = jwt.decode(token.strip(), options={"verify_signature": False})
        return UUID(str(claims["sub"]))
    except (jwt.PyJWTError, KeyError, ValueError, TypeError):
        return None


def ensure_users_hook(db: SessionFactory) -> RequestHook:
    """`httpx` request hook: the subject of the Bearer token gets a user row first."""

    async def hook(request: httpx.Request) -> None:
        learner_id = _bearer_subject(request)
        if learner_id is not None:
            await ensure_user(db, learner_id)

    return hook


async def login(client: httpx.AsyncClient, db: Db, learner_id: UUID, settings: Settings) -> str:
    """A `full` session of `learner_id` and its cookie on `client`; the token."""
    token = await open_session(db, settings, learner_id=learner_id, now=datetime.now(UTC))
    client.cookies.set(SESSION_COOKIE, token)
    return token
