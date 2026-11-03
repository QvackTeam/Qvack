"""Inputs of the teacher context read by stream B itself (ТЗ Ф4 WP14.1; Т-§10.1, Т-§9.5,
Т-§12.5, Т-§17.8). D-B-174.

- **Profile** (slot 3): explicit preferences — the last `preference.set` of each key; the teacher
  manner — `manner` of the last `digest.written` of the domain. What was learned about the learner
  (`learned*`) is a projection of stream A and comes from `quack.graph.read`.
- **Snapshot** (Т-§10.1): slots 3 and 4 are taken at the session start — the profile is the
  state of the log up to the first `session.started` of the session (a resumed session keeps it).
- **Plan** (slot 6): the document `content.session_plans` of the session (WP13.6).
- **Learner skill** (Т-§17.8): `/name` gives the instruction of the last version of the skill of
  that name, read by own SQL (no import of `artifacts`, WP14.1).
"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from pydantic import BaseModel

from quack.db.db import Db
from quack.events.event_types import DigestWritten, PreferenceSet
from quack.events.log import StoredEvent
from quack.events.records import PlanUpdateRecord
from quack.session.teacher_context import LearnerSkill, Profile

PROFILE_EVENTS = ("preference.set", "digest.written")

_COLUMNS = (
    "learner_id, seq, id, type, schema_version, actor, domain_id, session_id, causation_seq, "
    "correlation_id, idempotency_key, payload_hash, occurred_at, payload, source_refs"
)
_PROFILE = (
    f"SELECT {_COLUMNS} FROM core.events WHERE learner_id = %(learner_id)s "
    "AND type = ANY(%(types)s) AND seq <= %(up_to)s ORDER BY seq"
)
_SESSION_START = (
    "SELECT min(seq) AS seq FROM core.events WHERE learner_id = %(learner_id)s "
    "AND session_id = %(session_id)s AND type = 'session.started'"
)
_PLAN = (
    "SELECT plan FROM content.session_plans "
    "WHERE session_id = %(session_id)s AND learner_id = %(learner_id)s"
)
_LEARNER_SKILL = (
    "SELECT name, instruction FROM content.learner_skills "
    "WHERE learner_id = %(learner_id)s AND name = %(name)s ORDER BY version DESC LIMIT 1"
)


class _Seq(BaseModel):
    seq: int | None


def learner_profile(events: Sequence[StoredEvent], domain_id: UUID) -> Profile:
    """Slot 3 from the log (`events` in seq order); `learned` is filled from memory."""
    preferences: dict[str, str | int | float | bool] = {}
    manner: str | None = None
    for event in events:
        if event.type == "preference.set":
            preference = PreferenceSet.model_validate(event.payload)
            preferences[preference.key] = preference.value
        elif event.type == "digest.written":
            digest = DigestWritten.model_validate(event.payload)
            if digest.domain_id == domain_id:
                manner = digest.manner
    return Profile(preferences=preferences, manner=manner)


async def session_start_seq(db: Db, *, learner_id: UUID, session_id: UUID) -> int:
    """The seq of the first `session.started` of the session: the moment of the snapshot."""
    row = await db.fetch_one(
        _SESSION_START, {"learner_id": learner_id, "session_id": session_id}, row=_Seq
    )
    if row is None or row.seq is None:
        raise LookupError(f"session {session_id} has no session.started")
    return row.seq


async def load_profile(db: Db, *, learner_id: UUID, domain_id: UUID, up_to_seq: int) -> Profile:
    """The profile as of `up_to_seq`: the snapshot (the start of the session) or now."""
    params = {"learner_id": learner_id, "types": list(PROFILE_EVENTS), "up_to": up_to_seq}
    events = await db.fetch_all(_PROFILE, params, row=StoredEvent)
    return learner_profile(events, domain_id)


async def load_plan(db: Db, *, learner_id: UUID, session_id: UUID) -> PlanUpdateRecord | None:
    row = await db.fetch_one(_PLAN, {"learner_id": learner_id, "session_id": session_id})
    return None if row is None else PlanUpdateRecord.model_validate(row["plan"])


async def load_learner_skill(db: Db, *, learner_id: UUID, name: str) -> LearnerSkill | None:
    """`/name` of the action (`skill_invocation`); an unknown name gives nothing."""
    row = await db.fetch_one(_LEARNER_SKILL, {"learner_id": learner_id, "name": name})
    return None if row is None else LearnerSkill(name=row["name"], text=row["instruction"])
