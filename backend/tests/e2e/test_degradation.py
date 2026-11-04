"""E2E: the journey survives Redis and LLM outages (ТЗ Фазы 3 §8.7: T-E8, T-E9)."""

from __future__ import annotations

import asyncio
from uuid import UUID, uuid5

from sqlalchemy import text

from quack.graph.ids import QUACK_UUID_NS
from tests.e2e.journey import first, ok, onboard, turn
from tests.e2e.system import System


async def test_journey_without_redis(system_without_redis: System) -> None:
    """T-E8: with Redis down in API and workers the journey still works; the turn lock falls
    back to the advisory lock; the rate limiter counts locally; the projector polls."""
    system = system_without_redis
    learner = await system.register()
    domain_id, topic_id = await onboard(system, learner, "te8")
    session = ok(
        await system.client.post(
            "/v1/sessions",
            json={
                "domain_id": str(domain_id),
                "topic_id": str(topic_id),
                "idempotency_key": "te8:s",
            },
            headers=learner.headers,
        ),
        201,
    )
    session_id = UUID(session["session_id"])
    for n in range(2):
        events = await turn(system, learner, session_id, f"step {n}", f"te8:t{n}")
        assert first(events, "turn_completed") is not None

    gate = system.llm.hold("TeacherOutput")
    running = asyncio.create_task(turn(system, learner, session_id, "three", "te8:t3"))
    await asyncio.wait_for(gate.arrived.wait(), timeout=10)
    parallel = await system.client.post(
        f"/v1/sessions/{session_id}/turns",
        json={"text": "parallel", "idempotency_key": "te8:t4"},
        headers=learner.headers,
    )
    gate.release.set()
    await asyncio.wait_for(running, timeout=30)
    assert parallel.status_code == 409, parallel.text
    assert parallel.json()["error"]["code"] == "TURN_LOCKED"

    ok(
        await system.client.post(
            f"/v1/sessions/{session_id}/finish",
            json={"idempotency_key": "te8:finish"},
            headers=learner.headers,
        )
    )
    await system.settle()

    # Local rate limiter: learner_actions_per_min actions of a fresh learner pass, the next one
    # is 429 (the `auth` limit went with `/v1/auth/login`, ТЗ Ф4 WP18.3; D-A-113).
    limited = await system.register()
    limit = system.settings.learner_actions_per_min
    statuses = [
        (
            await system.client.patch(
                "/v1/learner/preferences",
                json={"key": "n", "value": i, "idempotency_key": f"te8:limit:{i}"},
                headers=limited.headers,
            )
        ).status_code
        for i in range(limit + 1)
    ]
    assert 429 not in statuses[: limit - 1], statuses
    assert statuses[-1] == 429, statuses

    async with system.session_factory() as s:
        lag = (
            await s.execute(
                text(
                    "SELECT s.last_seq, p.applied_seq FROM core.learner_seq s "
                    "JOIN ops.projector_offsets p USING (learner_id) WHERE s.learner_id = :l"
                ),
                {"l": learner.learner_id},
            )
        ).one()
    assert lag.applied_seq == lag.last_seq


async def test_journey_without_llm(system_without_llm: System) -> None:
    """T-E9: the model is down for the whole journey; every step degrades deterministically."""
    system = system_without_llm
    api = system.client
    learner = await system.register()
    h = learner.headers
    domain_id, topic_id = await onboard(system, learner, "te9")
    # The bank task `onboard()` leaves (D-A-209): the only candidate, so the pick is not a draw.
    task_id = uuid5(QUACK_UUID_NS, f"{domain_id}:bank-task")
    await system.settle()

    session = ok(
        await api.post(
            "/v1/sessions",
            json={
                "domain_id": str(domain_id),
                "topic_id": str(topic_id),
                "idempotency_key": "te9:s",
            },
            headers=h,
        ),
        201,
    )
    session_id = UUID(session["session_id"])
    events = await turn(system, learner, session_id, "Teach me", "te9:t1")
    completed = first(events, "turn_completed")
    assigned = first(events, "task_assigned")
    started = first(events, "turn_started")
    assert completed is not None and started is not None
    assert completed["degraded_mode"] == "llm_unavailable"
    assert assigned is not None and assigned["task_id"] == str(task_id), events

    submitted = ok(
        await api.post(
            f"/v1/sessions/{session_id}/tasks/{task_id}/submit",
            json={"turn_id": started["turn_id"], "answer": "A", "idempotency_key": "te9:submit"},
            headers=h,
        )
    )
    assert submitted["evaluator"] == "compute"

    ok(
        await api.post(
            f"/v1/sessions/{session_id}/finish", json={"idempotency_key": "te9:f"}, headers=h
        )
    )
    await system.settle()
    async with system.session_factory() as s:
        digests = await s.scalar(
            text(
                "SELECT count(*) FROM core.artifacts WHERE learner_id = :l AND kind = 'digest' "
                "AND session_id = :s"
            ),
            {"l": learner.learner_id, "s": session_id},
        )
    assert digests == 1
