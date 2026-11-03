"""Inputs of the teacher context read by stream B (ТЗ Ф4 WP14.1; Т-§12.5, Т-§17.8): the plan
and the learner skill. D-B-174."""

from __future__ import annotations

import json
from uuid import uuid4

from quack.db import Db
from quack.events.records import PlanUpdateRecord
from quack.session.teacher_context import LearnerSkill
from quack.session.turn_inputs import (
    load_learner_skill,
    load_plan,
)
from tests.db.fixtures import create_learner

DOMAIN = uuid4()
OTHER_DOMAIN = uuid4()


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
