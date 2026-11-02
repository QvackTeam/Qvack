"""Google OIDC through `authlib` (Т-§19.1, ТЗ Ф4 WP18.2).

The learner is found by the verified mail address of the id token; an unverified address is
refused. Secrets `GOOGLE_OIDC_CLIENT_ID`, `GOOGLE_OIDC_CLIENT_SECRET` live only in `api`.
The test double is `tests.support.oidc.FakeOIDC` (§8.1).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from quack.config import Settings
from quack.db import Db


class EmailNotVerified(Exception):
    """The id token carries an address Google has not verified."""


@dataclass(frozen=True)
class GoogleIdentity:
    email: str
    email_verified: bool


class GoogleOIDC(Protocol):
    def authorize_url(self, *, state: str) -> str:
        """Where `GET /auth/google/start` redirects."""
        ...

    async def identity(self, *, code: str) -> GoogleIdentity:
        """Exchange the code of `GET /auth/google/callback` for the id token's identity."""
        ...


class AuthlibGoogleOIDC:
    """`GoogleOIDC` on `authlib` with redirect URI `google_oidc_redirect_url` (Д-§3.1)."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def authorize_url(self, *, state: str) -> str:
        raise NotImplementedError

    async def identity(self, *, code: str) -> GoogleIdentity:
        raise NotImplementedError


async def learner_for_google(db: Db, identity: GoogleIdentity) -> UUID:
    """The learner of the verified address (a new row for a new one); `EmailNotVerified`."""
    raise NotImplementedError
