"""Inputs of the teacher context read by stream B itself (ТЗ Ф4 WP14.1; Т-§12.5, Т-§17.8).
D-B-174.

- **Plan** (slot 6): the document `content.session_plans` of the session (WP13.6).
- **Learner skill** (Т-§17.8): `/name` gives the instruction of the last version of the skill of
  that name, read by own SQL (no import of `artifacts`, WP14.1).

The profile and the goals of slots 3 and 4 come from memory (`GraphReader.profile`,
`domain_goals`, stream A's answer in #125), not from here.
"""

from __future__ import annotations

from uuid import UUID

from quack.db.db import Db
from quack.events.records import PlanUpdateRecord
from quack.session.teacher_context import LearnerSkill

_PLAN = (
    "SELECT plan FROM content.session_plans "
    "WHERE session_id = %(session_id)s AND learner_id = %(learner_id)s"
)
_LEARNER_SKILL = (
    "SELECT name, instruction FROM content.learner_skills "
    "WHERE learner_id = %(learner_id)s AND name = %(name)s ORDER BY version DESC LIMIT 1"
)


async def load_plan(db: Db, *, learner_id: UUID, session_id: UUID) -> PlanUpdateRecord | None:
    row = await db.fetch_one(_PLAN, {"learner_id": learner_id, "session_id": session_id})
    return None if row is None else PlanUpdateRecord.model_validate(row["plan"])


async def load_learner_skill(db: Db, *, learner_id: UUID, name: str) -> LearnerSkill | None:
    """`/name` of the action (`skill_invocation`); an unknown name gives nothing."""
    row = await db.fetch_one(_LEARNER_SKILL, {"learner_id": learner_id, "name": name})
    return None if row is None else LearnerSkill(name=row["name"], text=row["instruction"])
