"""Steps of the learner journey over HTTP: the onboarding (domain, structure, diagnostic).

The session half of the Phase 3 journey (`/turns`, `tasks/next`, `finish`) left with the
routes (ТЗ Ф4 §8.15; D-B-210); `T-E1` on the Phase 4 path is WP26.1."""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid5

import httpx

from quack.events.append import append_events
from quack.events.models import NewEvent
from quack.graph.ids import QUACK_UUID_NS
from tests.e2e.system import Learner, System
from tests.session.helpers import parse_sse

# A word of the learner's own reply, found by full-text search afterwards.
ANSWER_WORD = "gradientwombat"


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
