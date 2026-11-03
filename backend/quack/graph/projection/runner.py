"""The batch of one learner, `rules@3` (ТЗ Ф4 WP3.3; Т-§2.4; D-A-181).

Under the learner's advisory lock (the same rebuild and deletion take): the watermark from
`Learner.projectedSeq`, the next `projector_batch_size` events after it, the slice their handlers
declared, phase A, then the difference and the new watermark in one Neo4j transaction; the copy
of the watermark in `ops.projector_offsets` after the commit. An event the projector cannot
apply stops the learner's stream with a row in `ops.projector_failures`; `resume` removes it.
Phase B folds the skills the batch touched (WP4); misconceptions, the profile and topics
(WP5–WP6) plug in after it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from neo4j import AsyncDriver

from quack.config import Settings
from quack.db import Db
from quack.db.db import LockKeyspace
from quack.events.log import StoredEvent
from quack.graph.projection.misconception_fold import MisconceptionParams
from quack.graph.projection.phase_a import EventFailed, apply_events, batch_need
from quack.graph.projection.phase_b import (
    fold_dirty_misconceptions,
    fold_dirty_skills,
    fold_dirty_topics,
)
from quack.graph.projection.skill_fold import FoldParams
from quack.graph.projection.store import (
    load_fold_inputs,
    load_slice,
    load_topic_inputs,
    read_watermark,
    write_batch,
)
from quack.graph.projection.topic_fold import TopicParams
from quack.graph.projection.types import NodeRef
from quack.graph.projection.view import BatchSlice, Need, RulesParams

# WP3.6: the version of handlers, folds and parameters written on `Learner.projectorVersion`.
RULES_VERSION = "rules@3"

_EVENT_COLUMNS = (
    "learner_id, seq, id, type, schema_version, actor, domain_id, session_id, causation_seq, "
    "correlation_id, idempotency_key, payload_hash, occurred_at, payload, source_refs"
)
_EVENTS_AFTER = (
    "SELECT " + _EVENT_COLUMNS + " FROM core.events "
    "WHERE learner_id = %(learner_id)s AND seq > %(after)s ORDER BY seq LIMIT %(limit)s"
)
_EVENTS_BY_SEQ = (
    "SELECT " + _EVENT_COLUMNS + " FROM core.events "
    "WHERE learner_id = %(learner_id)s AND seq = ANY(%(seqs)s) ORDER BY seq"
)
_FAILURE = "SELECT seq, error FROM ops.projector_failures WHERE learner_id = %(learner_id)s"
_RECORD_FAILURE = (
    "INSERT INTO ops.projector_failures (learner_id, seq, error) "
    "VALUES (%(learner_id)s, %(seq)s, %(error)s) "
    "ON CONFLICT (learner_id) DO UPDATE SET seq = EXCLUDED.seq, error = EXCLUDED.error"
)
_RESUME = "DELETE FROM ops.projector_failures WHERE learner_id = %(learner_id)s"
_OFFSET = (
    "INSERT INTO ops.projector_offsets (learner_id, seq) VALUES (%(learner_id)s, %(seq)s) "
    "ON CONFLICT (learner_id) DO UPDATE SET seq = GREATEST(ops.projector_offsets.seq, EXCLUDED.seq)"
)

type Status = Literal["applied", "empty", "stopped", "failed", "busy"]


@dataclass(frozen=True)
class BatchOutcome:
    """`busy` — another projector, rebuild or deletion holds the learner; `stopped` — the stream
    stands on a failure; `failed` — this batch stopped it."""

    status: Status
    applied_seq: int
    failed_seq: int | None = None


def _event_refs(need: Need, events: dict[int, StoredEvent]) -> set[NodeRef]:
    refs: set[NodeRef] = set()
    for seq, field_name, label in need.event_refs:
        event = events.get(seq)
        value = event.payload.get(field_name) if event is not None else None
        if isinstance(value, str):
            refs.add((label, value))
    return refs


async def project_learner(
    db: Db, neo4j: AsyncDriver, settings: Settings, learner_id: UUID
) -> BatchOutcome:
    """Apply the next batch of one learner (Т-§2.4). A temporary Neo4j error propagates: the
    caller repeats the batch with a growing pause."""
    params = {"learner_id": learner_id}
    async with db.advisory_lock(LockKeyspace.LEARNER_PROJECTION, learner_id) as acquired:
        if not acquired:
            return BatchOutcome("busy", 0)
        watermark = await read_watermark(neo4j, str(learner_id))
        after = watermark[0] if watermark is not None else 0
        failure = await db.fetch_one(_FAILURE, params)
        if failure is not None:
            return BatchOutcome("stopped", after, int(failure["seq"]))
        limit = settings.projector_batch_max_events
        events = await db.fetch_all(
            _EVENTS_AFTER, params | {"after": after, "limit": limit}, row=StoredEvent
        )
        if not events:
            return BatchOutcome("empty", after)
        try:
            need = batch_need(events)
            in_batch = {e.seq for e in events}
            wanted = sorted(need.events - in_batch)
            earlier = await db.fetch_all(_EVENTS_BY_SEQ, params | {"seqs": wanted}, row=StoredEvent)
            known = {e.seq: e for e in [*earlier, *events]}
            loaded = await load_slice(neo4j, str(learner_id), need, _event_refs(need, known))
            batch = BatchSlice(
                str(learner_id), loaded, earlier, RulesParams.from_settings(settings)
            )
            apply_events(events, batch)
            # Phase B (WP4, WP5.2): folds of the skills and misconceptions the batch touched.
            dirty, wrong = batch.dirty_skills(), batch.dirty_misconceptions()
            if dirty or wrong:
                batch.extend(await load_fold_inputs(neo4j, str(learner_id), dirty, wrong))
                fold_dirty_skills(batch, dirty, FoldParams.from_settings(settings), events[-1].seq)
                fold_dirty_misconceptions(batch, wrong, MisconceptionParams.from_settings(settings))
            # Phase C (WP6.1, WP6.2): the topics of what changed.
            topics, skills, hubs = batch.topic_seeds()
            if topics or skills or hubs:
                loaded, topics = await load_topic_inputs(
                    neo4j, str(learner_id), topics, skills, hubs
                )
                batch.extend(loaded)
                levels = {k: list(v) for k, v in settings.control_type_levels.items()}
                fold_dirty_topics(batch, topics, TopicParams(control_type_levels=levels))
        except EventFailed as failed:
            await db.execute(
                _RECORD_FAILURE, params | {"seq": failed.seq, "error": repr(failed.cause)[:2000]}
            )
            return BatchOutcome("failed", after, failed.seq)
        last = events[-1].seq
        await write_batch(neo4j, str(learner_id), batch.diff(), last, RULES_VERSION)
        await db.execute(_OFFSET, params | {"seq": last})
        return BatchOutcome("applied", last)


async def resume(db: Db, learner_id: UUID) -> None:
    """`ops resume` (WP9.6, S15): the stopped stream of the learner goes on from its failure."""
    await db.execute(_RESUME, {"learner_id": learner_id})
