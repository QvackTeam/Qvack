"""Inputs of the teacher context read by stream B (ТЗ Ф4 WP14.1; Т-§10.1, Т-§9.5, Т-§17.8):
the profile from the log, the snapshot at the session start, the plan, the learner skill.
D-B-174."""

from __future__ import annotations

import json
from uuid import UUID, uuid4

import pytest

from quack.db import Db
from quack.events.event_types import DigestWritten, PreferenceSet, SessionStarted
from quack.events.log import NewEvent, append_events
from quack.events.records import DigestStructuredRecord, PlanUpdateRecord
from quack.events.registry import EventPayload
from quack.session.teacher_context import LearnerSkill, Profile
from quack.session.turn_inputs import (
    load_learner_skill,
    load_plan,
    load_profile,
    session_start_seq,
)
from tests.db.fixtures import create_learner

DOMAIN = uuid4()
OTHER_DOMAIN = uuid4()


async def _add(db: Db, learner_id: UUID, type_: str, payload: EventPayload, actor: str) -> int:
    session_id = getattr(payload, "session_id", None)
    new = NewEvent(
        type=type_,
        payload=payload,
        actor=actor,
        idempotency_key=str(uuid4()),
        session_id=session_id,
    )
    (stored,) = await append_events(db, learner_id, [new])
    return stored.seq


def _lang(value: str) -> PreferenceSet:
    return PreferenceSet(key="lang", value=value)


def _digest(domain_id: UUID, manner: str) -> DigestWritten:
    return DigestWritten(
        domain_id=domain_id,
        text="digest",
        as_of_seq=1,
        structured=DigestStructuredRecord(
            frontier=[], gap_hypotheses=[], uncertainty=None, moves=[], forecast=[]
        ),
        plan_divergence=False,
        manner=manner,
    )


async def test_profile_snapshot_at_the_session_start(pg_db: Db) -> None:
    """Т-§10.1, Т-§9.5: the last preference of each key and the manner of the last digest of
    the domain; the snapshot is the state at the first `session.started` (a resume keeps it)."""
    learner_id = await create_learner(pg_db)
    session_id = uuid4()
    await _add(
        pg_db, learner_id, "preference.set", PreferenceSet(key="lang", value="ru"), "learner"
    )
    await _add(pg_db, learner_id, "digest.written", _digest(DOMAIN, "short steps"), "analyst@1")
    await _add(pg_db, learner_id, "digest.written", _digest(OTHER_DOMAIN, "other"), "analyst@1")
    started = SessionStarted(session_id=session_id, domain_id=DOMAIN, intent="learn")
    start = await _add(pg_db, learner_id, "session.started", started, "learner")
    await _add(
        pg_db, learner_id, "preference.set", PreferenceSet(key="lang", value="en"), "learner"
    )
    resumed = started.model_copy(update={"resumed": True})
    await _add(pg_db, learner_id, "session.started", resumed, "system")
    await _add(pg_db, learner_id, "digest.written", _digest(DOMAIN, "more examples"), "analyst@1")

    assert await session_start_seq(pg_db, learner_id=learner_id, session_id=session_id) == start
    at_start = await load_profile(pg_db, learner_id=learner_id, domain_id=DOMAIN, up_to_seq=start)
    assert at_start == Profile(preferences={"lang": "ru"}, manner="short steps")
    now = await load_profile(pg_db, learner_id=learner_id, domain_id=DOMAIN, up_to_seq=10**9)
    assert now == Profile(preferences={"lang": "en"}, manner="more examples")
    stranger = await create_learner(pg_db)
    empty = await load_profile(pg_db, learner_id=stranger, domain_id=DOMAIN, up_to_seq=10**9)
    assert empty == Profile()
    with pytest.raises(LookupError):
        await session_start_seq(pg_db, learner_id=stranger, session_id=session_id)


async def test_plan_and_learner_skill(pg_db: Db) -> None:
    """Slot 6 — the plan document of the session; `/name` — the last version of the skill of
    that name; nothing of another learner."""
    learner_id = await create_learner(pg_db)
    stranger = await create_learner(pg_db)
    session_id = uuid4()
    assert await load_plan(pg_db, learner_id=learner_id, session_id=session_id) is None
    plan = PlanUpdateRecord(
        completed_steps=["idea"],
        current_step="example",
        next_steps=["task"],
        branches=[],
        cancel_request_ids=[],
    )
    await pg_db.execute(
        "INSERT INTO content.session_plans (session_id, learner_id, plan, status) "
        "VALUES (%(s)s, %(l)s, %(p)s, 'active')",
        {"s": session_id, "l": learner_id, "p": json.dumps(plan.model_dump(mode="json"))},
    )
    assert await load_plan(pg_db, learner_id=learner_id, session_id=session_id) == plan
    assert await load_plan(pg_db, learner_id=stranger, session_id=session_id) is None

    skill_id = uuid4()
    await pg_db.executemany(
        "INSERT INTO content.learner_skills (skill_id, version, learner_id, name, instruction) "
        "VALUES (%(s)s, %(v)s, %(l)s, 'quiz', %(i)s)",
        [
            {"s": skill_id, "v": 1, "l": learner_id, "i": "three questions"},
            {"s": skill_id, "v": 2, "l": learner_id, "i": "five questions"},
        ],
    )
    found = await load_learner_skill(pg_db, learner_id=learner_id, name="quiz")
    assert found == LearnerSkill(name="quiz", text="five questions")
    assert await load_learner_skill(pg_db, learner_id=learner_id, name="other") is None
    assert await load_learner_skill(pg_db, learner_id=stranger, name="quiz") is None
