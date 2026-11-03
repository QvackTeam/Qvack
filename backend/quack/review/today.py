"""«Сегодня», prep mode and the grade after a deadline (ТЗ Ф4 WP17.2, WP17.4, WP17.5; Т-§14).

`today` is synchronous code at the opening of a domain (`Т-§14.4`): the review candidates of
the core (`quack.graph.read.review_candidates`, WP17.1) of this domain only (`П-3.2`), at most
`today_max_items` with a priority above `today_min_score`; nothing important — an empty answer.
A non-empty show is `today.shown` keyed by the domain, the learner's date and the items, so the
dispatcher prepares the plan once (`today.prepare`, WP16.8). Every read is of the learner's own
nodes; another learner's id is «not found» (law 1).
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from neo4j import AsyncDriver
from pydantic import BaseModel, ConfigDict, Field
from redis.asyncio import Redis

from quack.config import Settings
from quack.db import Db
from quack.db.neo4j import literal, read_session
from quack.events.log import NewEvent, append_events
from quack.graph.read import create_graph_reader

type ItemReason = Literal["due", "consolidation", "misconception", "deadline"]
_REASONS: dict[str, ItemReason] = {
    "retention": "due",
    "consolidation": "consolidation",
    "misconception_recheck": "misconception",
    "hub_requirement": "deadline",
}

_SKILLS = (
    "MATCH (s:Skill) WHERE s.learnerId = $learner AND s.id IN $ids AND s.domainId = $domain "
    "OPTIONAL MATCH (t:Topic)-[:COVERS]->(s) RETURN s.id AS skill, t.id AS topic"
)
_DOMAIN = "MATCH (d:Domain {id: $id}) WHERE d.learnerId = $learner RETURN count(d) AS n"
_PAST_DEADLINES = (
    "MATCH (d:Domain {id: $domain})-[:HAS_HUB]->(h:Hub) WHERE d.learnerId = $learner "
    "AND h.deadlineAtMs > 0 AND h.deadlineAtMs < $today_ms RETURN h.id AS hub"
)
_HUB = "MATCH (h:Hub {id: $id}) WHERE h.learnerId = $learner RETURN h.domainId AS domain"
_TIMEZONE = (
    "SELECT settings->>'timezone' AS tz FROM core.learners WHERE learner_id = %(learner_id)s"
)
_GRADED = (
    "SELECT DISTINCT payload->>'hub_id' AS hub FROM core.events "
    "WHERE learner_id = %(learner_id)s AND type = 'grade.reported'"
)
_LAST_PREP = (
    "SELECT seq, type FROM core.events WHERE learner_id = %(learner_id)s "
    "AND type IN ('prep_mode.enabled', 'prep_mode.disabled') AND payload->>'hub_id' = %(hub)s "
    "ORDER BY seq DESC LIMIT 1"
)


class TodayEntry(BaseModel):
    skill_id: UUID
    topic_id: UUID | None = None
    reasons: list[ItemReason]
    score: float


class TodayView(BaseModel):
    """Empty `items` — no plaque (`Т-§14.4`). `grade_hub_ids` — hubs whose date has passed
    and that have no grade yet: the offer to enter it (WP17.5)."""

    items: list[TodayEntry] = []
    minutes: float = 0.0
    grade_hub_ids: list[UUID] = []


class PrepMode(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool


class Grade(BaseModel):
    model_config = ConfigDict(extra="forbid")
    grade: str = Field(min_length=1, max_length=40)
    scale: str = Field(min_length=1, max_length=40)


class Accepted(BaseModel):
    seq: int


async def _learner_today(db: Db, learner_id: UUID, now: datetime) -> datetime:
    """The learner's date by `core.learners.settings.timezone` (WP17.3), UTC by default."""
    row = await db.fetch_one(_TIMEZONE, {"learner_id": learner_id})
    zone = UTC
    if row is not None and row["tz"]:
        try:
            zone = ZoneInfo(str(row["tz"]))
        except (ZoneInfoNotFoundError, ValueError):
            zone = UTC
    local = now.astimezone(zone)
    return local.replace(hour=0, minute=0, second=0, microsecond=0)


async def today(
    db: Db,
    neo4j: AsyncDriver,
    redis: Redis | None,
    settings: Settings,
    learner_id: UUID,
    domain_id: UUID,
    now: datetime,
) -> TodayView | None:
    learner = str(learner_id)
    async with read_session(neo4j) as session:
        found = await (
            await session.run(literal(_DOMAIN), id=str(domain_id), learner=learner)
        ).single()
        if found is None or int(found["n"]) == 0:
            return None
    reader = create_graph_reader(neo4j, settings, learner_id=learner_id, db=db)
    candidates = await reader.review_candidates(learner_id, int(now.timestamp() * 1000))
    ids = [str(c.skill_id) for c in candidates]
    async with read_session(neo4j) as session:
        result = await session.run(
            literal(_SKILLS), learner=learner, ids=ids, domain=str(domain_id)
        )
        homes = {r["skill"]: r["topic"] async for r in result}
    chosen = sorted(
        (
            c
            for c in candidates
            if str(c.skill_id) in homes and c.priority > settings.today_min_score
        ),
        key=lambda c: (-c.priority, str(c.skill_id)),
    )[: settings.today_max_items]
    items = [
        TodayEntry(
            skill_id=c.skill_id,
            topic_id=UUID(homes[str(c.skill_id)]) if homes[str(c.skill_id)] else None,
            reasons=sorted({_REASONS[r] for r in c.reasons}),
            score=round(c.priority, 6),
        )
        for c in chosen
    ]
    day = await _learner_today(db, learner_id, now)
    async with read_session(neo4j) as session:
        result = await session.run(
            literal(_PAST_DEADLINES), domain=str(domain_id), learner=learner,
            today_ms=int(day.timestamp() * 1000),
        )  # fmt: skip
        past = {r["hub"] async for r in result}
    graded = {r["hub"] for r in await db.fetch_all(_GRADED, {"learner_id": learner_id})}
    if items:
        payload = {"domain_id": str(domain_id), "items": [i.model_dump(mode="json") for i in items]}
        digest = hashlib.sha256(str(payload["items"]).encode()).hexdigest()[:16]
        key = f"today:{domain_id}:{day.date().isoformat()}:{digest}"
        event = NewEvent(type="today.shown", payload=payload, actor="system",
                         idempotency_key=key, domain_id=domain_id)  # fmt: skip
        await append_events(db, learner_id, [event], redis=redis)
    return TodayView(
        items=items,
        minutes=round(settings.review_item_minutes * len(items), 2),
        grade_hub_ids=sorted(UUID(h) for h in past - graded),
    )


async def _own_hub(neo4j: AsyncDriver, learner_id: UUID, hub_id: UUID) -> bool:
    async with read_session(neo4j) as session:
        result = await session.run(literal(_HUB), id=str(hub_id), learner=str(learner_id))
        return await result.single() is not None


async def set_prep_mode(
    db: Db, neo4j: AsyncDriver, redis: Redis | None, learner_id: UUID, hub_id: UUID, enabled: bool
) -> int | None:
    """`prep_mode.enabled/disabled {hub_id}` (WP17.4); asking for the mode the hub already has
    returns its event — no new one (law 5)."""
    if not await _own_hub(neo4j, learner_id, hub_id):
        return None
    kind = "prep_mode.enabled" if enabled else "prep_mode.disabled"
    last = await db.fetch_one(_LAST_PREP, {"learner_id": learner_id, "hub": str(hub_id)})
    if last is not None and last["type"] == kind:
        return int(last["seq"])
    key = f"{kind}:{hub_id}:{0 if last is None else int(last['seq'])}"
    event = NewEvent(
        type=kind, payload={"hub_id": str(hub_id)}, actor="learner", idempotency_key=key
    )
    [stored] = await append_events(db, learner_id, [event], redis=redis)
    return stored.seq


async def report_grade(
    db: Db, neo4j: AsyncDriver, redis: Redis | None, learner_id: UUID, hub_id: UUID, body: Grade
) -> int | None:
    """`grade.reported {hub_id, grade, scale}` (WP17.5); the hub stays."""
    if not await _own_hub(neo4j, learner_id, hub_id):
        return None
    payload = {"hub_id": str(hub_id), "grade": body.grade, "scale": body.scale}
    key = f"grade.reported:{hub_id}:{body.grade}:{body.scale}"
    event = NewEvent(type="grade.reported", payload=payload, actor="learner", idempotency_key=key)
    [stored] = await append_events(db, learner_id, [event], redis=redis)
    return stored.seq
