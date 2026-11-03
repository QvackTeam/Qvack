"""Steps of the learner journey over HTTP: the onboarding (domain, structure, diagnostic).

The session half of the Phase 3 journey (`/turns`, `tasks/next`, `finish`) left with the
routes (ТЗ Ф4 §8.15; D-B-210); `T-E1` on the Phase 4 path is WP26.1."""

from __future__ import annotations

from typing import Any
from uuid import UUID

import httpx

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


async def onboard(system: System, learner: Learner, key: str) -> tuple[UUID, UUID]:
    """Domain → structure propose/confirm → diagnostic (start, 2 answers, finish)."""
    api, h = system.client, learner.headers
    domain = ok(
        await api.post(
            "/v1/domains", json={"name": "Calculus", "idempotency_key": f"{key}:d"}, headers=h
        ),
        201,
    )
    domain_id = UUID(domain["domain_id"])
    proposal = ok(
        await api.post(
            f"/v1/domains/{domain_id}/structure/propose",
            json={
                "goals": "Pass the exam",
                "background": "School algebra",
                "focus_areas": ["Basics", "Next steps"],
                "idempotency_key": f"{key}:propose",
            },
            headers=h,
        ),
        200,
        201,
    )
    ok(
        await api.post(
            f"/v1/domains/{domain_id}/structure/confirm",
            json={
                "structure_version": proposal["structure_version"],
                "idempotency_key": f"{key}:confirm",
            },
            headers=h,
        ),
        200,
        201,
    )
    topic_id = UUID(proposal["topics"][0]["topic_id"])
    await system.settle()

    started = ok(
        await api.post(
            f"/v1/domains/{domain_id}/diagnostic/start",
            json={"idempotency_key": f"{key}:diag"},
            headers=h,
        ),
        200,
        201,
    )
    diag_session = started["session_id"]
    question: dict[str, Any] | None = started["next_question"]
    for n in range(2):
        assert question is not None, "diagnostic ended before two answers"
        answer = ok(
            await api.post(
                f"/v1/domains/{domain_id}/diagnostic/answer",
                json={
                    "session_id": diag_session,
                    "task_id": question["task_id"],
                    "answer": (question.get("options") or ["A"])[0],
                    "confidence_self_report": 0.7,
                    "idempotency_key": f"{key}:diag:a{n}",
                },
                headers=h,
            )
        )
        question = answer.get("next_question")
    ok(
        await api.post(
            f"/v1/domains/{domain_id}/diagnostic/finish",
            json={"session_id": diag_session, "idempotency_key": f"{key}:diag:finish"},
            headers=h,
        )
    )
    await system.settle()
    return domain_id, topic_id
