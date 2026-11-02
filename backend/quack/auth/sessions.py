"""Sessions and the cookie (Т-§19.1, ТЗ Ф4 WP18.3).

An opaque token; the database keeps its hash with the learner, the scope (`full`, or
`companion` for the phone of one canvas, WP22.1), the expiry `auth_session_ttl_days` and the
revocation time. `learner_id` comes only from the session, never from a request body.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Literal
from uuid import UUID

from quack.auth.links import new_token, token_hash
from quack.config import Settings
from quack.db import Db

type Scope = Literal["full", "companion"]

# D-C-111: the documents name the flags and the domain of the cookie, not its name.
SESSION_COOKIE = "quack_session"


@dataclass(frozen=True)
class AuthSession:
    learner_id: UUID
    scope: Scope
    canvas_id: UUID | None
    expires_at: datetime


async def open_session(
    db: Db,
    settings: Settings,
    *,
    learner_id: UUID,
    now: datetime,
    scope: Scope = "full",
    canvas_id: UUID | None = None,
) -> str:
    """A new session; returns the token for the cookie."""
    token = new_token()
    await db.execute(
        "INSERT INTO core.auth_sessions "
        "(token_hash, learner_id, scope, canvas_id, created_at, expires_at) "
        "VALUES (%(hash)s, %(learner)s, %(scope)s, %(canvas)s, %(now)s, %(expires)s)",
        {
            "hash": token_hash(token),
            "learner": learner_id,
            "scope": scope,
            "canvas": canvas_id,
            "now": now,
            "expires": now + timedelta(days=settings.auth_session_ttl_days),
        },
    )
    return token


async def resolve_session(db: Db, *, token: str, now: datetime) -> AuthSession | None:
    """The live session of the token; `None` if unknown, expired or revoked."""
    row = await db.fetch_one(
        "SELECT learner_id, scope, canvas_id, expires_at FROM core.auth_sessions "
        "WHERE token_hash = %(hash)s AND revoked_at IS NULL AND expires_at > %(now)s",
        {"hash": token_hash(token), "now": now},
    )
    if row is None:
        return None
    return AuthSession(
        learner_id=row["learner_id"],
        scope=row["scope"],
        canvas_id=row["canvas_id"],
        expires_at=row["expires_at"],
    )


async def revoke_session(db: Db, *, token: str, now: datetime) -> None:
    """`POST /auth/logout`: the next request with this token is 401."""
    await db.execute(
        "UPDATE core.auth_sessions SET revoked_at = %(now)s "
        "WHERE token_hash = %(hash)s AND revoked_at IS NULL",
        {"hash": token_hash(token), "now": now},
    )


def cookie_params(settings: Settings) -> dict[str, Any]:
    """Arguments of `Response.set_cookie`: `HttpOnly`, `Secure`, `SameSite=Lax`,
    `Domain = session_cookie_domain`, max age `auth_session_ttl_days` (Т-§19.1)."""
    return {
        "key": SESSION_COOKIE,
        "httponly": True,
        "secure": True,
        "samesite": "lax",
        "domain": settings.session_cookie_domain,
        "max_age": settings.auth_session_ttl_days * 24 * 3600,
        "path": "/",
    }
