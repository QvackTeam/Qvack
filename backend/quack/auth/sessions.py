"""Sessions and the cookie (Т-§19.1, ТЗ Ф4 WP18.3).

An opaque token; the database keeps its hash with the learner, the scope (`full`, or
`companion` for the phone of one canvas, WP22.1), the expiry `auth_session_ttl_days` and the
revocation time. `learner_id` comes only from the session, never from a request body.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

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
    raise NotImplementedError


async def resolve_session(db: Db, *, token: str, now: datetime) -> AuthSession | None:
    """The live session of the token; `None` if unknown, expired or revoked."""
    raise NotImplementedError


async def revoke_session(db: Db, *, token: str, now: datetime) -> None:
    """`POST /auth/logout`: the next request with this token is 401."""
    raise NotImplementedError


def cookie_params(settings: Settings) -> dict[str, Any]:
    """Arguments of `Response.set_cookie`: `HttpOnly`, `Secure`, `SameSite=Lax`,
    `Domain = session_cookie_domain`, max age `auth_session_ttl_days` (Т-§19.1)."""
    raise NotImplementedError
