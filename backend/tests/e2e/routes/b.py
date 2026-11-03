"""Routes of stream B (ТЗ Ф4 §7.3): sessions, turns, actions, practice, `domains/classify`.

Stages 130-180 and 290: the learner's session; every step starts from the onboarding domain and
topic (`restore`), because the structure steps of stream A change them.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from quack.events.log import NewEvent, append_events
from quack.session.sessions import StartSession, start_session
from tests.e2e.journey import first
from tests.e2e.routes import NO_ID, Ids, Route, Stream

if TYPE_CHECKING:
    from tests.e2e.system import Learner, System

ONBOARDED = ("domain_id", "topic_id")


async def _action_session(system: System, learner: Learner, ids: Ids, payload: Any) -> Ids:
    """WP13.1: a Phase 4 session (its domain in the Phase 4 log) for the action route."""
    db, domain_id = system.resources.db, uuid4()
    created = NewEvent(
        type="domain.created",
        payload={"domain_id": str(domain_id), "name": "Actions"},
        actor="learner",
        idempotency_key=f"te2:domain:{domain_id}",
    )
    await append_events(db, learner.learner_id, [created])
    started = await start_session(
        db,
        learner_id=learner.learner_id,
        body=StartSession(domain_id=domain_id, intent="learn", idempotency_key=uuid4()),
    )
    return ids.replace(action_session_id=started.session_id)


async def _started_session(system: System, learner: Learner, ids: Ids, payload: Any) -> Ids:
    return ids.replace(session_id=UUID(payload["session_id"]))


async def _turn_taken(system: System, learner: Learner, ids: Ids, payload: Any) -> Ids:
    started = first(payload, "turn_started")
    assert started is not None
    return ids.replace(turn_id=UUID(started["turn_id"]))


async def _task_given(system: System, learner: Learner, ids: Ids, payload: Any) -> Ids:
    return ids.replace(task_id=UUID(payload["task_id"]))


STREAM = Stream(
    name="b",
    ids={
        "session_id": NO_ID,
        "task_id": NO_ID,
        "turn_id": NO_ID,
        # WP13.1: a Phase 4 session for the action route while the session routes are Phase 3.
        "action_session_id": NO_ID,
    },
    routes=(
        Route(
            "POST",
            "/v1/sessions",
            stage=130,
            restore=ONBOARDED,
            body=lambda ids, v: {
                "domain_id": str(ids.domain_id),
                "mode": ["learn", "practice"][v],
            },
            advance=_started_session,
        ),
        Route(
            "POST",
            "/v1/sessions/{session_id}/turns",
            stage=140,
            restore=ONBOARDED,
            requires=("session_id",),
            body=lambda ids, v: {"text": ["Hello", "Bye"][v]},
            advance=_turn_taken,
        ),
        Route(
            "POST",
            "/v1/sessions/{session_id}/tasks/next",
            stage=150,
            restore=ONBOARDED,
            requires=("session_id", "turn_id"),
            body=lambda ids, v: {
                "topic_id": str(ids.topic_id),
                "turn_id": str(ids.turn_id),
                "kind": ["choice", "open"][v],
            },
            advance=_task_given,
        ),
        Route(
            "POST",
            "/v1/sessions/{session_id}/tasks/{task_id}/hint",
            stage=160,
            restore=ONBOARDED,
            requires=("session_id", "task_id", "turn_id"),
            body=lambda ids, v: {"turn_id": str(ids.turn_id if v == 0 else ids.session_id)},
        ),
        Route(
            "POST",
            "/v1/sessions/{session_id}/tasks/{task_id}/submit",
            stage=170,
            restore=ONBOARDED,
            requires=("session_id", "task_id", "turn_id"),
            body=lambda ids, v: {"turn_id": str(ids.turn_id), "answer": ["A", "B"][v]},
            advance=_action_session,
        ),
        # ТЗ Ф4 WP13.1: an action without a teacher turn answers `201 {seq}` (D-B-156); the
        # key is a UUID. The session is a Phase 4 one (`_action_session`).
        Route(
            "POST",
            "/v1/sessions/{session_id}/actions",
            stage=180,
            restore=ONBOARDED,
            requires=("action_session_id",),
            path_ids={"session_id": "action_session_id"},
            body_key="uuid",
            body=lambda ids, v: {"kind": "confidence", "target_seq": 1, "value": [2, 3][v]},
        ),
        Route(
            "POST",
            "/v1/sessions/{session_id}/finish",
            stage=290,
            restore=ONBOARDED,
            requires=("session_id",),
            body=lambda ids, v: {},
            no_other_body="the body has no field besides the key",
        ),
        Route(
            "POST",
            "/v1/sessions/{session_id}/heartbeat",
            no_key="no event; refreshes presence only",
            body_key="none",
            body=lambda ids, v: {},
        ),
        # ТЗ Ф4 WP16.4: the body is `{text | material_id}` only; a direct model call, nothing is
        # written (D-B-173).
        Route(
            "POST",
            "/v1/domains/classify",
            no_key="no event; a direct classifier call that writes nothing",
        ),
    ),
    other_routes=frozenset(
        {
            ("GET", "/v1/sessions"),
            ("GET", "/v1/sessions/active"),
            ("GET", "/v1/sessions/{session_id}"),
            ("GET", "/v1/sessions/{session_id}/events"),
            ("GET", "/v1/sessions/{session_id}/jobs"),
        }
    ),
    routers=("quack.session.router:router",),
)
