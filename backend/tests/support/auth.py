"""Auth helpers of the tests (ТЗ Ф4 WP18.3, D-C-112 п.2, D-A-113).

Every route signs in with a Phase 4 session: a `core.auth_sessions` row and its cookie. Tests
that hold the learner sign in with `login` (the cookie on the client) or `session_cookie` (the
cookie on one request). Tests that act for many learners on one client mark a request with
`learner_headers(learner_id)`; `login_hook` on the client opens a session for that learner once
and sends its cookie instead of the mark, as `login` would. The API never reads the mark.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from uuid import UUID

import httpx
from sqlalchemy import text

from quack.api.auth import SESSION_COOKIE
from quack.auth.sessions import open_session
from quack.config import Settings
from quack.db import Db
from quack.db.postgres import SessionFactory

type RequestHook = Callable[[httpx.Request], Awaitable[None]]

TEST_LEARNER_HEADER = "X-Test-Learner"


_INSERT_USER = text(
    "INSERT INTO auth.users (id, email, password_hash, display_name) "
    "VALUES (:id, :email, 'test-only', 'Test learner') ON CONFLICT (id) DO NOTHING"
)


async def ensure_user(db: SessionFactory, learner_id: UUID) -> None:
    """The Phase 3 account row of `learner_id` (no-op when it exists): `DELETE /v1/learner` and
    `PATCH /v1/learner/preferences` still work on `auth.users` until WP1.3/WP25."""
    async with db() as session, session.begin():
        await session.execute(
            _INSERT_USER, {"id": learner_id, "email": f"{learner_id}@test.invalid"}
        )


async def login(client: httpx.AsyncClient, db: Db, learner_id: UUID, settings: Settings) -> str:
    """A `full` session of `learner_id` and its cookie on `client`; the token."""
    token = await open_session(db, settings, learner_id=learner_id, now=datetime.now(UTC))
    client.cookies.set(SESSION_COOKIE, token)
    return token


async def session_token(db: Db, learner_id: UUID, settings: Settings) -> str:
    """A `full` session of `learner_id`; the token for `session_cookie`."""
    return await open_session(db, settings, learner_id=learner_id, now=datetime.now(UTC))


def session_cookie(token: str) -> dict[str, str]:
    """Headers of one request signed in with the session `token`."""
    return {"Cookie": f"{SESSION_COOKIE}={token}"}


def learner_headers(learner_id: UUID) -> dict[str, str]:
    """Marks a request as made by `learner_id`; `login_hook` signs it in."""
    return {TEST_LEARNER_HEADER: str(learner_id)}


def login_hook(db: Db, settings: Settings) -> RequestHook:
    """`httpx` request hook: a request marked by `learner_headers` gets the cookie of a session
    of that learner (one session per learner per client) instead of the mark."""
    tokens: dict[UUID, str] = {}

    async def hook(request: httpx.Request) -> None:
        mark = request.headers.pop(TEST_LEARNER_HEADER, None)
        if mark is None:
            return
        learner_id = UUID(mark)
        if learner_id not in tokens:
            tokens[learner_id] = await session_token(db, learner_id, settings)
        request.headers["Cookie"] = f"{SESSION_COOKIE}={tokens[learner_id]}"

    return hook
