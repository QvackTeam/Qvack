"""Integration tests for Stream 1 Contour 1: Preferences and Two-Phase Account Deletion
(ТЗ §2.1, §3, §5; Т-§16.3, Т-§17.3, Т-§19, Т-§22.2). The learner signs in with a Phase 4
session (ТЗ Ф4 WP18.3, D-A-113); register, login and JWT are removed with their tests
(§8.15 п.1, `PHASE4_NOTES.md` «Правки тестов»).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import httpx
from sqlalchemy import text

from quack.db.postgres import SessionFactory
from quack.jobs import kinds
from quack.jobs.queue import enqueue_job
from tests.support.auth import session_cookie


async def _q(db: SessionFactory, sql: str, **params: Any) -> list[dict[str, Any]]:
    async with db() as session:
        return [dict(r) for r in (await session.execute(text(sql), params)).mappings()]


async def test_update_preferences_and_idempotency(
    api_client: httpx.AsyncClient,
    db: SessionFactory,
    seeded_learner: tuple[UUID, str],
) -> None:
    """3. `PATCH /v1/learner/preferences` updates `auth.users.preferences`, appends
    `learner.preferences_updated`, and handles idempotent retries with the same key.
    """
    learner_id, token = seeded_learner
    new_prefs = {"pace": "fast", "style": "socratic", "daily_goal_min": 45}

    resp = await api_client.patch(
        "/v1/learner/preferences",
        headers=session_cookie(token),
        json={"preferences": new_prefs, "idempotency_key": "prefs-key-1"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["preferences"] == new_prefs
    assert body["seq"] == 2

    [user_row] = await _q(
        db,
        "SELECT preferences FROM auth.users WHERE id = :id",
        id=learner_id,
    )
    assert user_row["preferences"] == new_prefs

    events = await _q(
        db,
        "SELECT seq, type, actor, idempotency_key, payload "
        "FROM core.events WHERE learner_id = :id AND type = 'learner.preferences_updated'",
        id=learner_id,
    )
    assert len(events) == 1
    assert events[0]["seq"] == 2
    assert events[0]["actor"] == "learner"
    assert events[0]["idempotency_key"] == "prefs-key-1"
    assert events[0]["payload"] == {"preferences": new_prefs}

    retry_resp = await api_client.patch(
        "/v1/learner/preferences",
        headers=session_cookie(token),
        json={"preferences": new_prefs, "idempotency_key": "prefs-key-1"},
    )
    assert retry_resp.status_code == 200
    assert retry_resp.json() == {"preferences": new_prefs, "seq": 2}

    events_after = await _q(
        db,
        "SELECT seq FROM core.events "
        "WHERE learner_id = :id AND type = 'learner.preferences_updated'",
        id=learner_id,
    )
    assert len(events_after) == 1


async def test_two_phase_account_deletion(
    api_client: httpx.AsyncClient,
    db: SessionFactory,
    seeded_learner: tuple[UUID, str],
) -> None:
    """5. `DELETE /v1/learner` marks `auth.users.deleted_at`, cancels queued jobs in `ops.jobs`,
    inserts `pending_purge` into `ops.deletion_tombstones`, and invalidates subsequent calls of
    the session (401 `UNAUTHENTICATED`, ТЗ Ф4 §4.5).
    """
    learner_id, token = seeded_learner
    async with db() as session, session.begin():
        job_id = await enqueue_job(
            session,
            kinds.graph_curate(learner_id, uuid4(), {"domain_id": str(uuid4())}, required_seq=None),
        )

    del_resp = await api_client.delete(
        "/v1/learner",
        headers=session_cookie(token),
    )
    assert del_resp.status_code == 200
    del_body = del_resp.json()
    assert del_body["status"] == "pending_purge"
    assert del_body["requested_at"]

    [user_row] = await _q(
        db,
        "SELECT deleted_at FROM auth.users WHERE id = :id",
        id=learner_id,
    )
    assert user_row["deleted_at"] is not None

    [tombstone] = await _q(
        db,
        "SELECT learner_id, requested_at, status FROM ops.deletion_tombstones "
        "WHERE learner_id = :id",
        id=learner_id,
    )
    assert tombstone["learner_id"] == learner_id
    assert tombstone["status"] == "pending_purge"
    assert tombstone["requested_at"] is not None

    [job_row] = await _q(
        db,
        "SELECT status FROM ops.jobs WHERE id = :id",
        id=job_id,
    )
    assert job_row["status"] == "cancelled"

    after = await api_client.patch(
        "/v1/learner/preferences",
        headers=session_cookie(token),
        json={"preferences": {"pace": "slow"}, "idempotency_key": "prefs-after-delete"},
    )
    assert after.status_code == 401
    assert after.json()["error"]["code"] == "UNAUTHENTICATED"
