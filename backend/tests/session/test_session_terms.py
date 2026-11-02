"""ТЗ Ф4 §8.9 T-TT1 (consent part), WP13.1, WP18.4: a session does not start without
`consent.given {kind: terms}` of the current `terms_version` — `403 CONSENT_REQUIRED`
(Т-§19.4). The gate is `quack.api.auth.require_terms` (stream C, D-C-112 п.3); the learner
has the Phase 3 token and the Phase 4 cookie session, as in the e2e system (D-C-115)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from uuid import UUID, uuid4

import httpx
import pytest
from neo4j import AsyncDriver
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine

from quack.api.app import create_app
from quack.api.auth import SESSION_COOKIE
from quack.auth.sessions import open_session
from quack.config import Settings
from quack.db.db import Db
from quack.db.postgres import SessionFactory
from quack.events.event_types import ConsentGiven
from quack.events.log import NewEvent, append_events
from tests.session.fixtures import SeededDomain
from tests.session.helpers import make_token
from tests.support.auth import ensure_users_hook
from tests.support.resources import build_app_resources

pytest_plugins = ["tests.session.fixtures"]

TERMS = "2026-11"


@pytest.fixture
def terms_settings(settings: Settings) -> Settings:
    return settings.model_copy(update={"terms_version": TERMS})


@pytest.fixture
async def gated(
    terms_settings: Settings,
    pg_engine: AsyncEngine,
    db: SessionFactory,
    neo4j: AsyncDriver,
    redis: Redis,
    pg_db: Db,
) -> AsyncIterator[httpx.AsyncClient]:
    """The app with the consent gate in place (no override of `require_terms`)."""
    resources = build_app_resources(
        terms_settings, pg_engine, neo4j, redis, session_factory=db, db=pg_db
    )
    app = create_app(terms_settings, resources=resources)
    transport = httpx.ASGITransport(app=app)
    hooks = {"request": [ensure_users_hook(db)]}
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test", event_hooks=hooks
    ) as http:
        yield http


async def _headers(pg_db: Db, settings: Settings, learner_id: UUID) -> dict[str, str]:
    await pg_db.execute(
        "INSERT INTO core.learners (learner_id, email) VALUES (%(l)s, %(e)s)",
        {"l": learner_id, "e": f"{learner_id}@test.invalid"},
    )
    cookie = await open_session(pg_db, settings, learner_id=learner_id, now=datetime.now(UTC))
    return {
        "Authorization": f"Bearer {make_token(settings, learner_id)}",
        "Cookie": f"{SESSION_COOKIE}={cookie}",
    }


async def _consent(pg_db: Db, learner_id: UUID, version: str) -> None:
    await append_events(
        pg_db,
        learner_id,
        [
            NewEvent(
                type="consent.given",
                payload=ConsentGiven(kind="terms", version=version),
                actor="learner",
                idempotency_key=f"consent:{uuid4()}",
            )
        ],
    )


def _start_body(seed: SeededDomain) -> dict[str, str]:
    return {"domain_id": str(seed.domain_id), "idempotency_key": str(uuid4())}


async def test_session_start_needs_current_terms(
    gated: httpx.AsyncClient,
    pg_db: Db,
    terms_settings: Settings,
    seeded_domain: SeededDomain,
) -> None:
    learner_id = seeded_domain.learner_id
    headers = await _headers(pg_db, terms_settings, learner_id)

    refused = await gated.post("/v1/sessions", json=_start_body(seeded_domain), headers=headers)
    assert refused.status_code == 403
    assert refused.json()["error"]["code"] == "CONSENT_REQUIRED"

    await _consent(pg_db, learner_id, "2025-01")  # an old version is not the current one
    stale = await gated.post("/v1/sessions", json=_start_body(seeded_domain), headers=headers)
    assert stale.status_code == 403

    await _consent(pg_db, learner_id, TERMS)
    started = await gated.post("/v1/sessions", json=_start_body(seeded_domain), headers=headers)
    assert started.status_code == 201, started.text


async def test_session_start_without_cookie_is_unauthenticated(
    gated: httpx.AsyncClient, terms_settings: Settings, seeded_domain: SeededDomain
) -> None:
    token = make_token(terms_settings, seeded_domain.learner_id)
    response = await gated.post(
        "/v1/sessions",
        json=_start_body(seeded_domain),
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 401
