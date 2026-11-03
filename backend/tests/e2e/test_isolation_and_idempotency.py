"""E2E: idempotency, isolation, concurrency (ТЗ Фазы 3 §8.7: T-E2, T-E3, T-E7)."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import Any
from uuid import UUID, uuid4

import httpx
from sqlalchemy import text

from quack.artifacts.cards import write_system_cards
from quack.artifacts.documents import Card, SystemBlock, write_system_blocks
from quack.canvas.boards import open_canvas
from quack.canvas.recognition import commit_typed
from quack.events import records
from quack.events.log import NewEvent, append_events
from quack.events.values import AnswerSpec, MathValue
from quack.practice.role_outputs import TaskCondition
from quack.practice.task_store import create_task
from tests.e2e.endpoints import (
    MULTIPART,
    NO_IDEMPOTENCY_KEY,
    Ids,
    body_for,
    mutating_routes,
    path_for,
)
from tests.e2e.journey import first, ok, onboard, run_journey, turn
from tests.e2e.system import Learner, System
from tests.session.helpers import parse_sse

# Order of the T-E2 walk: each step may use ids created by the previous ones.
IDEMPOTENT_WALK: tuple[tuple[str, str], ...] = (
    ("PATCH", "/v1/learner/preferences"),
    ("POST", "/v1/consents"),
    ("DELETE", "/v1/consents/research"),
    ("POST", "/v1/domains"),
    ("POST", "/v1/domains/{domain_id}/structure/propose"),
    ("POST", "/v1/domains/{domain_id}/structure/confirm"),
    ("PATCH", "/v1/domains/{domain_id}/structure"),
    ("PATCH", "/v1/domains/{domain_id}/topics/{topic_id}/status"),
    ("PATCH", "/v1/topics/{topic_id}/status"),
    ("POST", "/v1/domains/{domain_id}/diagnostic/start"),
    ("POST", "/v1/domains/{domain_id}/diagnostic/answer"),
    ("POST", "/v1/domains/{domain_id}/diagnostic/finish"),
    ("POST", "/v1/sessions"),
    ("POST", "/v1/sessions/{session_id}/turns"),
    ("POST", "/v1/sessions/{session_id}/tasks/next"),
    ("POST", "/v1/sessions/{session_id}/tasks/{task_id}/hint"),
    ("POST", "/v1/sessions/{session_id}/tasks/{task_id}/submit"),
    ("POST", "/v1/artifacts/notes"),
    ("PATCH", "/v1/artifacts/notes/{artifact_id}"),
    ("DELETE", "/v1/artifacts/notes/{artifact_id}"),
    ("PUT", "/v1/artifacts/{artifact_id}/blocks/{block_id}"),
    ("POST", "/v1/artifacts/{artifact_id}/blocks/{block_id}/accept"),
    ("DELETE", "/v1/artifacts/{artifact_id}/blocks/{block_id}"),
    ("PATCH", "/v1/cards/{card_id}"),
    ("DELETE", "/v1/cards/{card_id}"),
    ("POST", "/v1/canvases/{canvas_id}/lines/{line_id}/correct"),
    ("POST", "/v1/sessions/{session_id}/finish"),
    ("POST", "/v1/domains/{domain_id}/archive"),
)
# A body of these has no field besides the key, so "same key, other body" does not exist.
NO_OTHER_BODY = {
    ("POST", "/v1/domains/{domain_id}/diagnostic/start"),
    ("DELETE", "/v1/artifacts/notes/{artifact_id}"),
    ("POST", "/v1/artifacts/{artifact_id}/blocks/{block_id}/accept"),
    ("DELETE", "/v1/artifacts/{artifact_id}/blocks/{block_id}"),
    ("DELETE", "/v1/cards/{card_id}"),
    ("POST", "/v1/sessions/{session_id}/finish"),
}


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


def _placeholder_ids(domain_id: UUID, topic_id: UUID) -> Ids:
    zero = UUID(int=0)
    return Ids(domain_id, topic_id, zero, zero, zero, zero, zero, zero, 1)


async def test_mutating_endpoints_are_idempotent(system_for_walk: System) -> None:
    """T-E2: repeat with the same key and body → same answer, no new events; same key with
    another body → 409. Endpoints without a key are listed with a reason."""
    system = system_for_walk
    keyed = mutating_routes(system.app) - set(NO_IDEMPOTENCY_KEY)
    assert keyed == set(IDEMPOTENT_WALK), {
        "not walked": sorted(keyed - set(IDEMPOTENT_WALK)),
        "not mounted": sorted(set(IDEMPOTENT_WALK) - keyed),
    }

    learner = await system.register()
    main_domain, main_topic = await onboard(system, learner, "te2:main")
    ids = _placeholder_ids(main_domain, main_topic)

    for method, path in IDEMPOTENT_WALK:
        if path.startswith("/v1/sessions"):
            ids = replace(ids, domain_id=main_domain, topic_id=main_topic)
        key = f"te2:{method}:{path}"
        url = path_for(path, ids)
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
        if (method, path) not in NO_OTHER_BODY:
            other = await _send(
                system, learner, method, url, body_for(method, path, ids, key, variant=1)
            )
            assert other.status_code == 409, f"{method} {path}: {other.status_code} {other.text}"
            assert other.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"
        ids = await _advance(system, learner, ids, method, path, _payload(first_response))


async def _advance(
    system: System, learner: Learner, ids: Ids, method: str, path: str, payload: Any
) -> Ids:
    """Take the ids the walk needs next from a response."""
    if (method, path) == ("POST", "/v1/domains"):
        return replace(ids, domain_id=UUID(payload["domain_id"]))
    if path.endswith("/structure/propose"):
        return replace(
            ids,
            topic_id=UUID(payload["topics"][0]["topic_id"]),
            structure_version=payload["structure_version"],
        )
    if path.endswith("/structure/confirm"):
        await system.settle()
    if path.endswith("/diagnostic/start"):
        return replace(
            ids,
            diagnostic_session_id=UUID(payload["session_id"]),
            diagnostic_task_id=UUID(payload["next_question"]["task_id"]),
        )
    if (method, path) == ("POST", "/v1/sessions"):
        return replace(ids, session_id=UUID(payload["session_id"]))
    if path.endswith("/turns"):
        started = first(payload, "turn_started")
        assert started is not None
        return replace(ids, turn_id=UUID(started["turn_id"]))
    if path.endswith("/tasks/next"):
        return replace(ids, task_id=UUID(payload["task_id"]))
    if (method, path) == ("POST", "/v1/artifacts/notes"):
        return replace(ids, artifact_id=UUID(payload["artifact_id"]))
    if (method, path) == ("DELETE", "/v1/artifacts/notes/{artifact_id}"):
        return await _notes_of_phase4_topic(system, learner, ids)
    if (method, path) == ("PUT", "/v1/artifacts/{artifact_id}/blocks/{block_id}"):
        # WP23.1: the system adds a supplement to the learner's block; the walk accepts it.
        notes = await write_system_blocks(
            system.resources.db,
            learner_id=learner.learner_id,
            kind="notes",
            owner_id=ids.topic_id,
            blocks=[SystemBlock(block_id=ids.block_id, kind="summary", content="More")],
            created_by="artifact_writer@1",
        )
        return replace(ids, block_id=notes.blocks[1].block_id)
    if path.endswith("/accept"):
        return replace(ids, block_id=ids.learner_block_id)
    if (method, path) == ("DELETE", "/v1/artifacts/{artifact_id}/blocks/{block_id}"):
        ids = replace(ids, card_id=await _card_of_topic(system, learner, ids))
        return await _canvas_with_a_line(system, learner, ids)
    if (method, path) == ("PATCH", "/v1/cards/{card_id}"):
        return replace(ids, card_id=UUID(payload["cards"][0]["card_id"]))
    return ids


async def _canvas_with_a_line(system: System, learner: Learner, ids: Ids) -> Ids:
    """WP21.3: a canvas of a Phase 4 session with one typed line for the correction route."""
    db = system.resources.db
    session_id = uuid4()
    started = NewEvent(
        type="session.started",
        payload={"session_id": str(session_id), "domain_id": str(uuid4()), "intent": "learn"},
        actor="learner",
        idempotency_key=f"te2:session:{session_id}",
    )
    await append_events(db, learner.learner_id, [started])
    canvas = await open_canvas(db, learner_id=learner.learner_id, session_id=session_id)
    await commit_typed(
        db, learner_id=learner.learner_id, session_id=session_id, canvas_id=canvas.canvas_id,
        block_id="t1", latex="x=1", at_ms=0,
    )  # fmt: skip
    return replace(ids, canvas_id=canvas.canvas_id, line_id="t1")


async def _notes_of_phase4_topic(system: System, learner: Learner, ids: Ids) -> Ids:
    """WP23.1 reads topics from the Phase 4 log (`topic.created`), which the Phase 3 structure
    of the walk does not write (D-C-112): one topic is recorded there for the notes routes."""
    topic_id, domain_id = uuid4(), uuid4()
    await append_events(
        system.resources.db,
        learner.learner_id,
        [
            NewEvent(
                type="topic.created",
                payload={
                    "topic_id": topic_id,
                    "domain_id": domain_id,
                    "name": "Limits",
                    "origin": "session",
                },
                actor="code",
                idempotency_key=f"te2:topic:{topic_id}",
                domain_id=domain_id,
            )
        ],
    )
    notes = ok(await system.client.get(f"/v1/topics/{topic_id}/notes", headers=learner.headers))
    block_id = uuid4()
    return replace(
        ids,
        topic_id=topic_id,
        artifact_id=UUID(notes["artifact_id"]),
        learner_block_id=block_id,
        block_id=block_id,
    )


async def _card_of_topic(system: System, learner: Learner, ids: Ids) -> UUID:
    """WP23.4: a card of the walk's Phase 4 topic, as the writer leaves it — its task already in
    the bank (D-C-140)."""
    card_id = uuid4()
    await create_task(
        system.resources.db,
        learner_id=learner.learner_id,
        task_id=card_id,
        family_id=card_id,
        source="generated",
        condition=TaskCondition(text="Ratio test when?", latex=None),
        markup=records.TaskMarkupRecord(
            tests=[records.TestedLevelRecord(skill_id=uuid4(), level=3)],
            method_named=False,
            answer=AnswerSpec(type="number", value=MathValue(latex="1", sympy="1")),
        ),
        verification="unchecked",
        actor="artifact_writer@1",
        idempotency_key=f"te2:card:{card_id}",
    )
    card = Card(card_id=card_id, kind="sign_to_method", prompt="Ratio test when?", owner="system")
    await write_system_cards(
        system.resources.db,
        system.resources.settings,
        learner_id=learner.learner_id,
        topic_id=ids.topic_id,
        cards=[card],
        created_by="artifact_writer@1",
    )
    return card_id


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
    async with system.session_factory() as session:
        diag = (
            await session.execute(
                text(
                    "SELECT payload->>'session_id' AS sid FROM core.events "
                    "WHERE learner_id = :l AND type = 'diagnostic.started' LIMIT 1"
                ),
                {"l": a.learner_id},
            )
        ).one()
    ids = Ids(
        domain_id=j.domain_id,
        topic_id=j.topic_id,
        session_id=j.session_id,
        task_id=j.practice_task_id,
        turn_id=UUID(turn_started["turn_id"]),
        artifact_id=UUID(note["artifact_id"]),
        diagnostic_session_id=UUID(diag.sid),
        diagnostic_task_id=j.assigned_task_id,
        structure_version=1,
    )
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
        url = path_for(path, ids)
        if method == "GET":
            response = await system.client.get(url, headers=b.headers)
        elif (method, path) in MULTIPART:
            response = await system.client.request(
                method, url, files=MULTIPART[(method, path)], headers=b.headers
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
