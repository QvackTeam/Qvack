"""E2E: idempotency, isolation, concurrency (ТЗ Фазы 3 §8.7: T-E2, T-E3, T-E7)."""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import UUID, uuid4

import httpx
from sqlalchemy import text

from tests.e2e.endpoints import mutating_routes
from tests.e2e.journey import first, ok, onboard, run_journey, turn
from tests.e2e.routes import (
    Ids,
    body_for,
    files_for,
    form_for,
    isolation_prepares,
    no_key_routes,
    path_for,
    walk,
)
from tests.e2e.system import Learner, System
from tests.session.helpers import parse_sse


async def _events(system: System, learner_id: UUID) -> int:
    """Events of the learner in both logs: the Phase 3 one and, for the routes of WP18
    (consents), the Phase 4 one (D-C-115) until the whole API moves over (D-C-112)."""
    async with system.session_factory() as session:
        phase3 = int(
            await session.scalar(
                text("SELECT count(*) FROM core.events WHERE learner_id = :l"), {"l": learner_id}
            )
            or 0
        )
    row = await system.resources.db.fetch_one(
        "SELECT count(*) AS n FROM core.events WHERE learner_id = %(learner_id)s",
        {"learner_id": learner_id},
    )
    return phase3 + (0 if row is None else int(row["n"]))


async def _send(
    system: System, learner: Learner, method: str, url: str, body: dict[str, Any]
) -> httpx.Response:
    return await system.client.request(method, url, json=body, headers=learner.headers)


def _payload(response: httpx.Response) -> Any:
    if response.headers.get("content-type", "").startswith("text/event-stream"):
        return [(e, d) for e, d in parse_sse(response.content)]
    return response.json()


async def test_mutating_endpoints_are_idempotent(system_for_walk: System) -> None:
    """T-E2: repeat with the same key and body → same answer, no new events; same key with
    another body → 409. Endpoints without a key are listed with a reason."""
    system = system_for_walk
    steps = walk()
    keyed = mutating_routes(system.app) - set(no_key_routes())
    assert keyed == {r.key for r in steps}, {
        "not walked": sorted(keyed - {r.key for r in steps}),
        "not mounted": sorted({r.key for r in steps} - keyed),
    }

    learner = await system.register()
    main_domain, main_topic = await onboard(system, learner, "te2:main")
    onboarded = Ids(domain_id=main_domain, topic_id=main_topic)
    ids = onboarded

    for route in steps:
        method, path = route.key
        ids = ids.replace(**{name: getattr(onboarded, name) for name in route.restore})
        if route.prepare is not None:
            ids = await route.prepare(system, learner, ids)
        not_yet = [name for name in route.requires if ids.is_default(name)]
        assert not not_yet, f"{method} {path}: the walk has not created {not_yet} yet"
        key = f"te2:{method}:{path}"
        url = path_for(method, path, ids)
        body = body_for(method, path, ids, key)
        first_response = await _send(system, learner, method, url, body)
        assert first_response.status_code < 300, f"{method} {path}: {first_response.text}"
        # Background jobs of the step (turn, session finish) write events; let them land.
        await system.settle()
        before = await _events(system, learner.learner_id)
        again = await _send(system, learner, method, url, body)
        assert again.status_code == first_response.status_code, f"{method} {path}: {again.text}"
        assert _payload(again) == _payload(first_response), f"{method} {path}"
        assert await _events(system, learner.learner_id) == before, f"{method} {path}"
        if route.no_other_body is None:
            other = await _send(
                system, learner, method, url, body_for(method, path, ids, key, variant=1)
            )
            assert other.status_code == 409, f"{method} {path}: {other.status_code} {other.text}"
            assert other.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"
        if route.advance is not None:
            ids = await route.advance(system, learner, ids, _payload(first_response))


NOTE_WORD = "quokkasecret"


async def test_cross_learner_isolation(system: System) -> None:
    """T-E3: learner B with ids of learner A gets 404 on every route with an id in the path;
    A's data does not change; B's search does not see A's note."""
    j = await run_journey(system, "te3")
    a = j.learner
    note = ok(
        await system.client.post(
            "/v1/artifacts/notes",
            json={
                "domain_id": str(j.domain_id),
                "title": "Mine",
                "text": f"Remember the {NOTE_WORD}",
                "idempotency_key": "te3:note",
            },
            headers=a.headers,
        ),
        201,
    )
    turn_started = first(j.turns[-1], "turn_started")
    assert turn_started is not None
    ids = Ids(
        domain_id=j.domain_id,
        topic_id=j.topic_id,
        session_id=j.session_id,
        task_id=j.practice_task_id,
        turn_id=UUID(turn_started["turn_id"]),
        artifact_id=UUID(note["artifact_id"]),
    )
    for prepare in isolation_prepares():
        ids = await prepare(system, a, ids)
    await system.settle()
    a_events = await _events(system, a.learner_id)

    b = await system.register()
    with_ids = sorted(
        (method.upper(), path)
        for path, operations in system.app.openapi()["paths"].items()
        if path.startswith("/v1/") and "{" in path
        for method in operations
    )
    assert with_ids
    for method, path in with_ids:
        url = path_for(method, path, ids)
        files = files_for(method, path)
        if method == "GET":
            response = await system.client.get(url, headers=b.headers)
        elif files is not None:
            response = await system.client.request(
                method, url, files=files, data=form_for(method, path), headers=b.headers
            )
        else:
            body = body_for(method, path, ids, f"te3:b:{method}:{path}")
            response = await system.client.request(method, url, json=body, headers=b.headers)
        assert response.status_code == 404, (
            f"{method} {path}: {response.status_code} {response.text}"
        )
        assert response.json()["error"]["code"] == "NOT_FOUND", f"{method} {path}"

    await system.settle()
    assert await _events(system, a.learner_id) == a_events
    found = ok(
        await system.client.get("/v1/artifacts/search", params={"q": NOTE_WORD}, headers=b.headers)
    )
    assert found["artifact_hits"] == [] and found["event_hits"] == [], found


async def test_concurrency_invariants(system: System) -> None:
    """T-E7: a parallel turn of the same session is 409 TURN_LOCKED; two parallel session
    starts leave exactly one active session and no 5xx."""
    learner = await system.register()
    domain_id, topic_id = await onboard(system, learner, "te7")
    session = ok(
        await system.client.post(
            "/v1/sessions",
            json={
                "domain_id": str(domain_id),
                "topic_id": str(topic_id),
                "idempotency_key": "te7:s",
            },
            headers=learner.headers,
        ),
        201,
    )
    session_id = UUID(session["session_id"])

    gate = system.llm.hold("TeacherOutput")
    first_turn = asyncio.create_task(turn(system, learner, session_id, "one", "te7:t1"))
    await asyncio.wait_for(gate.arrived.wait(), timeout=10)
    second = await system.client.post(
        f"/v1/sessions/{session_id}/turns",
        json={"text": "two", "idempotency_key": "te7:t2"},
        headers=learner.headers,
    )
    gate.release.set()
    events = await asyncio.wait_for(first_turn, timeout=30)
    assert first(events, "turn_completed") is not None
    assert second.status_code == 409, second.text
    assert second.json()["error"]["code"] == "TURN_LOCKED"

    starts = await asyncio.gather(
        *(
            system.client.post(
                "/v1/sessions",
                json={"domain_id": str(domain_id), "idempotency_key": f"te7:par:{uuid4().hex}"},
                headers=learner.headers,
            )
            for _ in range(2)
        )
    )
    assert all(r.status_code in (200, 201) for r in starts), [r.text for r in starts]
    started_ids = {r.json()["session_id"] for r in starts}
    async with system.session_factory() as s:
        rows = (
            await s.execute(
                text("SELECT id, status FROM core.sessions WHERE learner_id = :l"),
                {"l": learner.learner_id},
            )
        ).all()
        abandoned_reason = await s.scalar(
            text(
                "SELECT payload->>'reason' FROM core.events WHERE learner_id = :l "
                "AND type = 'session.abandoned' AND payload->>'session_id' = ANY(:ids)"
            ),
            {"l": learner.learner_id, "ids": list(started_ids)},
        )
    statuses = {str(r.id): r.status for r in rows if str(r.id) in started_ids}
    assert sorted(statuses.values()) == ["abandoned", "active"], statuses
    assert sum(1 for r in rows if r.status == "active") == 1
    assert abandoned_reason == "superseded_by_new_session"
