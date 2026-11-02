"""Login by a link sent to the mail (Т-§19.1, ТЗ Ф4 WP18.1).

The token is 128 random bits; only its hash is stored (`core.auth_links`). The link lives
`auth_link_ttl_min` and is redeemed once. The answer to a request is the same for a known and
a new address. Limits per address and per IP: `LinkLimiter` (Redis, local without it).
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from redis.asyncio import Redis

from quack.api.email import EmailSender
from quack.config import Settings
from quack.db import Db


class LinkInvalid(Exception):
    """The token is unknown, expired or already redeemed."""


class AuthRateLimited(Exception):
    """Too many link requests for this address or IP within the hour (Т-§19.1)."""

    def __init__(self, retry_after_s: int) -> None:
        super().__init__(f"too many login link requests, retry in {retry_after_s} s")
        self.retry_after_s = retry_after_s


def new_token() -> str:
    """128 random bits, URL-safe."""
    raise NotImplementedError


def token_hash(token: str) -> str:
    """What the database keeps instead of a token."""
    raise NotImplementedError


class LinkLimiter:
    """`auth_link_per_email_per_hour` and `auth_link_per_ip_per_hour`: Redis counters, local
    counters when Redis is `None` or down (Т-§19.1, Д-§10)."""

    def __init__(self, redis: Redis | None, settings: Settings) -> None:
        self._redis = redis
        self._settings = settings

    async def hit(self, *, email: str, ip: str, now: datetime) -> None:
        """Count one request; `AuthRateLimited` over either limit."""
        raise NotImplementedError


async def request_link(
    db: Db,
    email_sender: EmailSender,
    limiter: LinkLimiter,
    settings: Settings,
    *,
    email: str,
    ip: str,
    verify_url: str,
    now: datetime,
) -> None:
    """Store the hash of a new token and mail `verify_url?token=…` to `email` (lower case).
    `verify_url` is the absolute URL of `GET /auth/link/verify` built by the router."""
    raise NotImplementedError


async def redeem_link(db: Db, *, token: str, now: datetime) -> UUID:
    """Redeem the token once; the learner of its address, a new `core.learners` row for a new
    address. `LinkInvalid` if unknown, expired or used."""
    raise NotImplementedError
