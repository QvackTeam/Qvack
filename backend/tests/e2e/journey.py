"""The full learner journey over HTTP (scenario of `T-E1`, reused by `T-E4`, `T-E10`)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID, uuid5

import httpx

from quack.events.append import append_events
from quack.events.models import NewEvent
from quack.graph.ids import QUACK_UUID_NS
from tests.e2e.system import Learner, System
from tests.session.helpers import parse_sse
from tests.support.compute import math_verdict

# A word of the learner's own reply, found by full-text search afterwards.
ANSWER_WORD = "gradientwombat"


@dataclass
class Journey:
    learner: Learner
    domain_id: UUID
    topic_id: UUID
    session_id: UUID
    assigned_task_id: UUID
    practice_task_id: UUID
    turns: list[list[tuple[str, dict[str, Any]]]] = field(default_factory=list)


def ok(response: httpx.Response, *codes: int) -> dict[str, Any]:
    assert response.status_code in (codes or (200,)), (
        f"{response.request.method} {response.request.url.path}: "
        f"{response.status_code} {response.text}"
    )
    return response.json()


def sse_events(response: httpx.Response) -> list[tuple[str, dict[str, Any]]]:
    assert response.status_code == 200, response.text
    return parse_sse(response.content)


def first(events: list[tuple[str, dict[str, Any]]], name: str) -> dict[str, Any] | None:
    return next((data for event, data in events if event == name), None)


def structure_node(domain_id: UUID, kind: str, slug: str) -> UUID:
    """The id of a node of the seeded Phase 3 structure: `kind` is `topic` or `skill`, `slug` one
    of `basics`, `next` (topics) and `basics-1`, `next-1` (their skills)."""
    return uuid5(QUACK_UUID_NS, f"{domain_id}:1:{kind}:{slug}")


async def _seed_phase3_structure(
    system: System, learner: Learner, domain_id: UUID, key: str
) -> UUID:
    """The structure of the domain in the Phase 3 log: the session routes of the stand still
    read it there until stream B moves them to `Db` (WP1.3, #222). Two topics with a skill each
    and one prerequisite, as the scripted `structurer` of Phase 3 gave; returns the first topic.
    The routes that wrote it (`…/structure/propose|confirm`) are gone (ТЗ Ф4 §2.3 row 5)."""

    topics = [
        (structure_node(domain_id, "topic", "basics"), "Basics"),
        (structure_node(domain_id, "topic", "next"), "Next steps"),
    ]
    skills = [
        (structure_node(domain_id, "skill", "basics-1"), topics[0][0], "Core idea"),
        (structure_node(domain_id, "skill", "next-1"), topics[1][0], "Applying the idea"),
    ]
    d = str(domain_id)
    events = [
        NewEvent(
            type="domain.created",
            actor="learner",
            domain_id=domain_id,
            idempotency_key=f"{key}:p3:domain",
            payload={"domain_id": d, "name": "Calculus", "slug": f"calculus-{d[:8]}"},
        ),
        NewEvent(
            type="structure.proposed",
            actor="structurer@1",
            domain_id=domain_id,
            idempotency_key=f"{key}:p3:propose",
            payload={
                "domain_id": d,
                "structure_version": 1,
                "topics": [{"topic_id": str(t), "name": n} for t, n in topics],
                "skills": [
                    {"skill_id": str(sk), "topic_id": str(t), "name": n} for sk, t, n in skills
                ],
                "prereqs": [{"from_topic_id": str(topics[0][0]), "to_topic_id": str(topics[1][0])}],
                "skill_deps": [],
                "misconceptions": [],
            },
        ),
        NewEvent(
            type="structure.confirmed",
            actor="learner",
            domain_id=domain_id,
            idempotency_key=f"{key}:p3:confirm",
            payload={"domain_id": d, "structure_version": 1},
        ),
        # What the diagnostic left in the task bank: the teacher assigns it on the first turn.
        NewEvent(
            type="task.generated",
            actor="system",
            domain_id=domain_id,
            idempotency_key=f"{key}:p3:task",
            payload={
                "task_id": str(uuid5(QUACK_UUID_NS, f"{domain_id}:bank-task")),
                "domain_id": d,
                "topic_id": str(topics[0][0]),
                "family_id": "bank-choice",
                "difficulty": 0.5,
                "kind": "choice",
                "prompt_text": "Pick A",
                "reference_solution": {"option": "A", "answer": "A", "options": ["A", "B"]},
                "target_skills": [{"skill": {"skill_id": str(skills[0][0])}, "weight": 1.0}],
            },
        ),
    ]
    async with system.session_factory() as session, session.begin():
        await append_events(session, learner.learner_id, events, publish_wakeup=False)
    return topics[0][0]


async def onboard(system: System, learner: Learner, key: str) -> tuple[UUID, UUID]:
    """The domain by `POST /v1/domains` (Phase 4) and its structure in the Phase 3 log, which
    the session routes still read (D-A-207). The interview of the structure and the diagnostic
    are removed with their routes (ТЗ Ф4 §2.3 row 5, §8.15 п.1)."""
    domain = ok(
        await system.client.post(
            "/v1/domains",
            json={"name": "Calculus", "idempotency_key": f"{key}:d"},
            headers=learner.headers,
        ),
        201,
    )
    domain_id = UUID(domain["domain_id"])
    topic_id = await _seed_phase3_structure(system, learner, domain_id, key)
    await system.settle()
    return domain_id, topic_id


async def turn(
    system: System,
    learner: Learner,
    session_id: UUID,
    text: str,
    key: str,
    *,
    related_task_id: UUID | None = None,
) -> list[tuple[str, dict[str, Any]]]:
    body: dict[str, Any] = {"text": text, "idempotency_key": key}
    if related_task_id is not None:
        body["related_task_id"] = str(related_task_id)
    return sse_events(
        await system.client.post(
            f"/v1/sessions/{session_id}/turns", json=body, headers=learner.headers
        )
    )


async def run_journey(system: System, key: str = "journey") -> Journey:
    """`T-E1` scenario up to the final `settle()`."""
    learner = await system.register()
    api, h = system.client, learner.headers
    domain_id, topic_id = await onboard(system, learner, key)
    system.compute.push(*(math_verdict(True) for _ in range(4)))

    session = ok(
        await api.post(
            "/v1/sessions",
            json={
                "domain_id": str(domain_id),
                "topic_id": str(topic_id),
                "idempotency_key": f"{key}:s",
            },
            headers=h,
        ),
        201,
    )
    session_id = UUID(session["session_id"])

    turns: list[list[tuple[str, dict[str, Any]]]] = []
    turns.append(await turn(system, learner, session_id, "Where do I start?", f"{key}:t1"))
    assigned = first(turns[0], "task_assigned")
    assert assigned is not None, f"no task assigned on the first turn: {turns[0]}"
    assigned_task_id = UUID(assigned["task_id"])
    turns.append(
        await turn(
            system,
            learner,
            session_id,
            f"A, because of the {ANSWER_WORD} rule",
            f"{key}:t2",
            related_task_id=assigned_task_id,
        )
    )
    turns.append(await turn(system, learner, session_id, "What next?", f"{key}:t3"))
    last_turn = first(turns[-1], "turn_started")
    assert last_turn is not None
    turn_id = last_turn["turn_id"]

    nxt = ok(
        await api.post(
            f"/v1/sessions/{session_id}/tasks/next",
            json={
                "topic_id": str(topic_id),
                "turn_id": turn_id,
                # the scripted `task_gen` answers a choice task (tests/support/llm.py)
                "kind": "choice",
                "idempotency_key": f"{key}:next",
            },
            headers=h,
        )
    )
    practice_task_id = UUID(nxt["task_id"])
    ok(
        await api.post(
            f"/v1/sessions/{session_id}/tasks/{practice_task_id}/hint",
            json={"turn_id": turn_id, "idempotency_key": f"{key}:hint"},
            headers=h,
        )
    )
    ok(
        await api.post(
            f"/v1/sessions/{session_id}/tasks/{practice_task_id}/submit",
            json={"turn_id": turn_id, "answer": "A", "idempotency_key": f"{key}:submit"},
            headers=h,
        )
    )
    ok(
        await api.post(
            f"/v1/sessions/{session_id}/finish",
            json={"idempotency_key": f"{key}:finish"},
            headers=h,
        )
    )
    await system.settle()
    return Journey(
        learner, domain_id, topic_id, session_id, assigned_task_id, practice_task_id, turns
    )
