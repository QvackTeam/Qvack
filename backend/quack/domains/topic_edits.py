"""Edits of topics and «я это уже знаю» (ТЗ Ф4 WP8.2; Т-§4.11).

Each edit checks that the topic (and the target topic, the episode) is the learner's — `404`
otherwise (law 1) — and appends one event; the projector and the dispatcher do the rest
(`topic.merged` — skills to the target and an alias, `episode.reassigned` — re-extraction,
`known.claimed` — `check.known_claim`). The requests of §6.4 carry no idempotency key, so the
key is the edit itself with the state it starts from: a retry gives the same event, a later
edit of the same kind a new one (law 5).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from neo4j import AsyncDriver
from pydantic import BaseModel, ConfigDict, Field
from redis.asyncio import Redis

from quack.db import Db
from quack.db.neo4j import literal, read_session
from quack.events.log import NewEvent, append_events

_TOPIC = (
    "MATCH (t:Topic {id: $id}) WHERE t.learnerId = $learner "
    "RETURN t.name AS name, t.domainId AS domain, t.knownClaimedAtMs AS known"
)
_EPISODE = (
    "SELECT 1 AS found FROM core.events WHERE learner_id = %(learner_id)s "
    "AND seq = %(seq)s AND type = 'episode.closed'"
)


class RenameTopic(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=200)


class MergeTopic(BaseModel):
    model_config = ConfigDict(extra="forbid")
    into: UUID


class ReassignEpisode(BaseModel):
    model_config = ConfigDict(extra="forbid")
    topic_id: UUID


class Edited(BaseModel):
    """The number of the appended event."""

    seq: int


async def _topic(neo4j: AsyncDriver, learner_id: UUID, topic_id: UUID) -> dict[str, Any] | None:
    async with read_session(neo4j) as session:
        result = await session.run(literal(_TOPIC), id=str(topic_id), learner=str(learner_id))
        record = await result.single()
    return None if record is None else dict(record)


async def _append(
    db: Db, redis: Redis | None, learner_id: UUID, kind: str, payload: dict[str, Any], key: str
) -> int:
    event = NewEvent(type=kind, payload=payload, actor="learner", idempotency_key=key)
    [stored] = await append_events(db, learner_id, [event], redis=redis)
    return stored.seq


async def rename(
    db: Db, neo4j: AsyncDriver, redis: Redis | None, learner_id: UUID, topic_id: UUID, name: str
) -> int | None:
    topic = await _topic(neo4j, learner_id, topic_id)
    if topic is None:
        return None
    payload = {"topic_id": str(topic_id), "name": name}
    key = f"topic.renamed:{topic_id}:{topic['name']}->{name}"
    return await _append(db, redis, learner_id, "topic.renamed", payload, key)


async def merge(
    db: Db, neo4j: AsyncDriver, redis: Redis | None, learner_id: UUID, topic_id: UUID, into: UUID
) -> int | None:
    """None — either topic is not the learner's, they are one topic or of different domains."""
    source = await _topic(neo4j, learner_id, topic_id)
    target = await _topic(neo4j, learner_id, into)
    if source is None or target is None or topic_id == into:
        return None
    if source["domain"] != target["domain"]:
        return None
    payload = {"from_id": str(topic_id), "into_id": str(into)}
    key = f"topic.merged:{topic_id}:{into}"
    return await _append(db, redis, learner_id, "topic.merged", payload, key)


async def hide(
    db: Db, neo4j: AsyncDriver, redis: Redis | None, learner_id: UUID, topic_id: UUID
) -> int | None:
    if await _topic(neo4j, learner_id, topic_id) is None:
        return None
    payload = {"topic_id": str(topic_id)}
    return await _append(db, redis, learner_id, "topic.hidden", payload, f"topic.hidden:{topic_id}")


async def claim_known(
    db: Db, neo4j: AsyncDriver, redis: Redis | None, learner_id: UUID, topic_id: UUID
) -> int | None:
    topic = await _topic(neo4j, learner_id, topic_id)
    if topic is None:
        return None
    key = f"known.claimed:{topic_id}:{topic['known'] or 0}"  # a later claim after a check: new
    return await _append(db, redis, learner_id, "known.claimed", {"topic_id": str(topic_id)}, key)


async def reassign(
    db: Db,
    neo4j: AsyncDriver,
    redis: Redis | None,
    learner_id: UUID,
    episode_seq: int,
    topic_id: UUID,
) -> int | None:
    """The episode is an `episode.closed` of the learner (its `seq`); the topic is theirs."""
    found = await db.fetch_one(_EPISODE, {"learner_id": learner_id, "seq": episode_seq})
    if found is None or await _topic(neo4j, learner_id, topic_id) is None:
        return None
    payload = {"episode_seq": episode_seq, "topic_id": str(topic_id)}
    key = f"episode.reassigned:{episode_seq}:{topic_id}"
    return await _append(db, redis, learner_id, "episode.reassigned", payload, key)
