"""Authentication of the API on Phase 4 sessions (ТЗ Ф4 WP18.3, WP18.4; D-C-112, D-A-113).

The password, JWT and `/v1/auth/register|login|me` of Phases 1–3 are removed (§2.3 row 3).
`get_current_learner_id` keeps its name and signature, so the routers of every stream stay as
they are; it reads the session cookie (`get_current_session`). Until the deletion moves to `Db`
(WP25) a learner with `auth.users.deleted_at` or a row in `ops.deletion_tombstones` is also
refused, as before (D-C-004).

Routers attach `get_current_learner_id` at router level, so a request without a session gets
`401 UNAUTHENTICATED` before body validation (T-A2). Tests override only this dependency.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated, Literal, Protocol
from uuid import UUID

from fastapi import Depends, Request
from sqlalchemy import text

from quack.api.errors import ApiError
from quack.api.resources import get_resources
from quack.config import Settings
from quack.db import Db

# Phase 3 deletion (D-C-004) until WP25 moves it to `Db`.
_DELETED_LEARNER_SQL = text(
    "SELECT 1 WHERE EXISTS (SELECT 1 FROM auth.users WHERE id = :id AND deleted_at IS NOT NULL) "
    "OR EXISTS (SELECT 1 FROM ops.deletion_tombstones WHERE learner_id = :id)"
)


async def get_current_learner_id(request: Request) -> UUID:
    """FastAPI dependency: the learner of the live session of the cookie, not deleted;
    `ApiError(UNAUTHENTICATED, 401)` otherwise."""
    session = await get_current_session(request)
    async with get_resources(request).session_factory() as db_session:
        deleted = await db_session.scalar(_DELETED_LEARNER_SQL, {"id": session.learner_id})
    if deleted is not None:
        raise _unauthenticated("learner deleted")
    return session.learner_id


# --- Sessions of Phase 4 (ТЗ Ф4 WP18.3, WP18.4) ------------------------------------------
# The session lives in `core.auth_sessions` (`quack.auth.sessions`, a product package). Routers
# of every stream depend on this module (API base, §4.1), so the product functions reach it
# through `app.state` set by the assembly (`quack.api.app`): `session_resolver`, `terms_checker`.

SESSION_COOKIE = "quack_session"  # D-C-111


@dataclass(frozen=True)
class CurrentSession:
    learner_id: UUID
    scope: Literal["full", "companion"]
    canvas_id: UUID | None
    expires_at: datetime


class SessionResolver(Protocol):
    async def __call__(self, db: Db, *, token: str, now: datetime) -> CurrentSession | None: ...


class TermsChecker(Protocol):
    async def __call__(self, db: Db, learner_id: UUID, settings: Settings) -> bool: ...


def _unauthenticated(message: str) -> ApiError:
    return ApiError("UNAUTHENTICATED", message, status_code=401)


async def get_current_session(request: Request) -> CurrentSession:
    """FastAPI dependency: the live session of the cookie; `401 UNAUTHENTICATED` without one.
    `learner_id` comes only from here, never from a request body (Т-§19.1)."""
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise _unauthenticated("not signed in")
    resolver: SessionResolver = request.app.state.session_resolver
    session = await resolver(get_resources(request).db, token=token, now=datetime.now(UTC))
    if session is None:
        raise _unauthenticated("session expired or signed out")
    return session


async def require_terms(
    request: Request, session: Annotated[CurrentSession, Depends(get_current_session)]
) -> None:
    """FastAPI dependency for starting a session (WP18.4): `403 CONSENT_REQUIRED` without
    `consent.given {kind: terms}` of the current `terms_version` (Т-§19.4). The session comes
    through `Depends`, so a route with both dependencies resolves the cookie once."""
    resources = get_resources(request)
    checker: TermsChecker = request.app.state.terms_checker
    if not await checker(resources.db, session.learner_id, resources.settings):
        raise ApiError("CONSENT_REQUIRED", "terms of use are not accepted", status_code=403)
