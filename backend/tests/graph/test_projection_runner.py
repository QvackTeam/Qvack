"""ТЗ Ф4 WP3.3, §8.4: the batch loop of `rules@3` on Postgres and Neo4j (D-A-181).

`test_unknown_type_stops_stream` — T-P6; materials and vectors reach Neo4j end to end (the
search of stream C reads `Chunk`, #135); batches of any size give one graph (part of T-P1).
"""

from __future__ import annotations

import base64
import struct
from typing import Any
from uuid import UUID, uuid4

import orjson
from neo4j import AsyncDriver
from redis.asyncio import Redis

from quack.config import Settings
from quack.db import Db
from quack.db.redis import projector_applied_channel
from quack.events.log import NewEvent, append_events
from quack.graph.projection.runner import RULES_VERSION, BatchOutcome, project_learner, resume
from tests.db.fixtures import create_learner


def _new(event_type: str, payload: dict[str, Any], key: str, **envelope: Any) -> NewEvent:
    return NewEvent(type=event_type, payload=payload, actor="code", idempotency_key=key, **envelope)


def _vector(values: list[float]) -> str:
    return base64.b64encode(struct.pack(f"<{len(values)}f", *values)).decode()


def _materials(
    domain: UUID, topic: UUID, skill: UUID, material: UUID, chunk: UUID
) -> list[NewEvent]:
    d = str(domain)
    return [
        _new("domain.created", {"domain_id": d, "name": "Algebra"}, "d", domain_id=domain),
        _new(
            "topic.created",
            {"topic_id": str(topic), "domain_id": d, "name": "Fractions", "origin": "session"},
            "t",
            domain_id=domain,
        ),
        _new(
            "skill.created",
            {
                "skill_id": str(skill),
                "topic_id": str(topic),
                "domain_id": d,
                "name": "add fractions",
                "summary": "s",
                "status": "active",
                "origin": "session",
            },
            "s",
            domain_id=domain,
        ),
        _new(
            "material.uploaded",
            {"material_id": str(material), "object_key": "k", "mime": "application/pdf"},
            "m",
            domain_id=domain,
        ),
        _new(
            "chunk.indexed",
            {
                "chunk_id": str(chunk),
                "material_id": str(material),
                "page": 4,
                "text": "a/b + c/d",
                "notation": ["a/b"],
                "teaches": [str(skill)],
                "uses": [],
            },
            "c",
            domain_id=domain,
        ),
        _new(
            "embedding.ready",
            {
                "node_kind": "chunk",
                "node_id": str(chunk),
                "model": "m",
                "dim": 2,
                "vector": _vector([0.5, -1.0]),
            },
            "e",
            domain_id=domain,
        ),
    ]


async def _project_all(db: Db, neo4j: AsyncDriver, settings: Settings, learner: UUID) -> list[str]:
    statuses: list[str] = []
    for _ in range(10):  # a watermark that does not move would loop forever
        outcome: BatchOutcome = await project_learner(db, neo4j, settings, learner)
        statuses.append(outcome.status)
        if outcome.status != "applied":
            break
    return statuses


async def _graph(neo4j: AsyncDriver, learner: UUID) -> tuple[set[Any], set[Any]]:
    async with neo4j.session() as session:
        nodes = await session.run(
            "MATCH (n {learnerId: $l}) RETURN labels(n)[0] AS label, n.id AS id, "
            "properties(n) AS props",
            l=str(learner),
        )
        found = {(r["label"], r["id"], repr(sorted(r["props"].items()))) async for r in nodes}
        rels = await session.run(
            "MATCH (a {learnerId: $l})-[r]->(b) RETURN a.id AS a, type(r) AS t, b.id AS b, "
            "properties(r) AS props",
            l=str(learner),
        )
        links = {(r["a"], r["t"], r["b"], repr(sorted(r["props"].items()))) async for r in rels}
    return found, links


async def test_materials_and_vectors_reach_neo4j(
    pg_db: Db, neo4j: AsyncDriver, settings: Settings
) -> None:
    learner = await create_learner(pg_db)
    domain, topic, skill, material, chunk = uuid4(), uuid4(), uuid4(), uuid4(), uuid4()
    await append_events(pg_db, learner, _materials(domain, topic, skill, material, chunk))

    outcome = await project_learner(pg_db, neo4j, settings, learner)
    assert (outcome.status, outcome.applied_seq) == ("applied", 6)
    async with neo4j.session() as session:
        found = await session.run(
            "MATCH (:Material {id: $m})-[:HAS_CHUNK]->(c:Chunk {id: $c})-[:TEACHES]->"
            "(:Skill {id: $s})<-[:COVERS]-(:Topic {id: $t})<-[:HAS_TOPIC]-(:Domain {id: $d}) "
            "MATCH (l:Learner {id: $l}) RETURN properties(c) AS c, properties(l) AS l",
            m=str(material),
            c=str(chunk),
            s=str(skill),
            t=str(topic),
            d=str(domain),
            l=str(learner),
        )
        row = await found.single()
    assert row is not None
    c = row["c"]
    assert (c["learnerId"], c["domainId"], c["searchable"]) == (str(learner), str(domain), True)
    assert c["embedding"] == [0.5, -1.0]
    assert (row["l"]["projectedSeq"], row["l"]["projectorVersion"]) == (6, RULES_VERSION)
    offset = await pg_db.fetch_one(
        "SELECT seq FROM ops.projector_offsets WHERE learner_id = %(learner_id)s",
        {"learner_id": learner},
    )
    assert offset is not None and offset["seq"] == 6
    async with neo4j.session() as session:
        found = await session.run(
            "MATCH (s:Skill {id: $s}) RETURN properties(s) AS s", s=str(skill)
        )
        state = (await found.single() or {"s": {}})["s"]
    # Phase B: a new skill gets every state property explicit (Т-§3.4.4, law 8).
    assert (state["l1Status"], state["l6Basis"], state["retState"], state["expCount"]) == (
        "unknown",
        "none",
        "none",
        0,
    )
    assert state["asOfSeq"] == 0  # no evidence or exposure rests on it yet
    async with neo4j.session() as session:
        found = await session.run(
            "MATCH (t:Topic {id: $t}) RETURN properties(t) AS t", t=str(topic)
        )
        shown = (await found.single() or {"t": {}})["t"]
    # Phase C: an active topic with nothing tested (Т-§8.6 rule 8), shown (Т-§4.7).
    assert (shown["displayState"], shown["visibility"], shown["nearestDueAtMs"]) == (
        "not_tested",
        "shown",
        0,
    )
    again = await project_learner(pg_db, neo4j, settings, learner)
    assert (again.status, again.applied_seq) == ("empty", 6)


async def test_batches_of_any_size_give_one_graph(
    pg_db: Db, neo4j: AsyncDriver, settings: Settings
) -> None:
    """Т-§2.5: applying in batches equals applying at once — the next batch reads what the
    earlier one wrote (the material of a chunk, the chunk of a vector)."""
    whole, small = await create_learner(pg_db), await create_learner(pg_db)
    await append_events(pg_db, whole, _materials(*[uuid4() for _ in range(5)]))
    await append_events(pg_db, small, _materials(*[uuid4() for _ in range(5)]))
    assert await _project_all(pg_db, neo4j, settings, whole) == ["applied", "empty"]
    two = settings.model_copy(update={"projector_batch_max_events": 2})
    assert await _project_all(pg_db, neo4j, two, small) == ["applied"] * 3 + ["empty"]
    whole_nodes, whole_rels = await _graph(neo4j, whole)
    small_nodes, small_rels = await _graph(neo4j, small)
    assert sorted(label for label, _, _ in whole_nodes) == sorted(
        label for label, _, _ in small_nodes
    )
    rel_types = sorted(t for _, t, _, _ in whole_rels)
    assert rel_types == sorted(t for _, t, _, _ in small_rels)
    assert rel_types == ["COVERS", "HAS_CHUNK", "HAS_HUB", "HAS_TOPIC", "OWNS", "TEACHES"]


async def test_unknown_type_stops_stream(pg_db: Db, neo4j: AsyncDriver, settings: Settings) -> None:
    """T-P6 (Т-§2.4): an unknown type — a row in `ops.projector_failures`, the learner's stream
    stands, other learners go on; `ops resume` lets it go on (after the code knows the type)."""
    broken, other = await create_learner(pg_db), await create_learner(pg_db)
    domain = uuid4()
    created = _new("domain.created", {"domain_id": str(domain), "name": "A"}, "d")
    renamed = _new("domain.created", {"domain_id": str(uuid4()), "name": "B"}, "x")
    await append_events(pg_db, broken, [created, renamed])
    await append_events(pg_db, other, [_new("domain.created", {"domain_id": str(uuid4()),
                                                               "name": "C"}, "d")])  # fmt: skip
    await pg_db.execute(
        "UPDATE core.events SET type = 'comet.sighted' "
        "WHERE learner_id = %(learner_id)s AND seq = 2",
        {"learner_id": broken},
    )

    failed = await project_learner(pg_db, neo4j, settings, broken)
    assert (failed.status, failed.applied_seq, failed.failed_seq) == ("failed", 0, 2)
    row = await pg_db.fetch_one(
        "SELECT seq, error FROM ops.projector_failures WHERE learner_id = %(learner_id)s",
        {"learner_id": broken},
    )
    assert row is not None and row["seq"] == 2 and "comet.sighted" in row["error"]
    stopped = await project_learner(pg_db, neo4j, settings, broken)
    assert (stopped.status, stopped.failed_seq) == ("stopped", 2)
    assert (await project_learner(pg_db, neo4j, settings, other)).status == "applied"
    nodes, _ = await _graph(neo4j, broken)
    assert nodes == set()  # the batch is applied whole or not at all

    await pg_db.execute(
        "UPDATE core.events SET type = 'domain.created' "
        "WHERE learner_id = %(learner_id)s AND seq = 2",
        {"learner_id": broken},
    )
    await resume(pg_db, broken)
    resumed = await project_learner(pg_db, neo4j, settings, broken)
    assert (resumed.status, resumed.applied_seq) == ("applied", 2)


async def test_rules3_stale_rebuild(pg_db: Db, neo4j: AsyncDriver, settings: Settings) -> None:
    """T-P8 (WP3.5, Д-§6.3): a learner with `projectorVersion = rules@2` is found by
    `--stale-rules`; the rebuild puts `rules@3` and the graph of the batch loop."""
    from quack.graph.projection.rebuild import rebuild_learner
    from quack.graph.projection.store import stale_learners

    learner = await create_learner(pg_db)
    await append_events(pg_db, learner, _materials(*[uuid4() for _ in range(5)]))
    await _project_all(pg_db, neo4j, settings, learner)
    projected = await _graph(neo4j, learner)
    async with neo4j.session() as session:
        await session.run(
            "MATCH (l:Learner {id: $l}) SET l.projectorVersion = 'rules@2' "
            "CREATE (:Skill {id: $junk, learnerId: $l})",
            l=str(learner),
            junk=str(uuid4()),
        )
    assert str(learner) in await stale_learners(neo4j, RULES_VERSION)
    outcome = await rebuild_learner(pg_db, neo4j, settings, learner)
    assert (outcome.status, outcome.applied_seq) == ("rebuilt", 6)
    assert str(learner) not in await stale_learners(neo4j, RULES_VERSION)
    rebuilt = await _graph(neo4j, learner)
    assert rebuilt == projected  # the junk is gone, the rest is the same graph


async def test_changed_topics_are_published_after_commit(
    pg_db: Db, neo4j: AsyncDriver, settings: Settings, redis: Redis
) -> None:
    """WP3.3 (`Т-§2.4`, ТЗ Ф4 §4.8): after the commit the batch publishes `applied_seq` and the
    topics it changed on `projector:applied:{learner}` — `projection_advanced` of the stream."""
    learner = await create_learner(pg_db)
    domain, topic, skill, material, chunk = uuid4(), uuid4(), uuid4(), uuid4(), uuid4()
    await append_events(pg_db, learner, _materials(domain, topic, skill, material, chunk))
    pubsub = redis.pubsub()
    await pubsub.subscribe(projector_applied_channel(learner))
    try:
        outcome = await project_learner(pg_db, neo4j, settings, learner, redis=redis)
        assert outcome.status == "applied", outcome
        message = None
        for _ in range(3):  # the first read may return the confirmation of the subscription
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=5.0)
            if message is not None:
                break
        assert message is not None
        assert orjson.loads(message["data"]) == {"applied_seq": 6, "topics": [str(topic)]}
    finally:
        await pubsub.aclose()


async def test_state_at_replays_the_log_with_rules3(
    pg_db: Db, neo4j: AsyncDriver, settings: Settings
) -> None:
    """WP8.3 (`Т-§2.6`, D-A-191): `state_at` replays the learner's events up to N with the
    handlers and folds of `rules@3` — before the verdict level 3 is not tested, after it is
    proven by a T1 of code."""
    from quack.graph.read.neo4j_reader import Neo4jGraphReader
    from tests.graph.test_projection_batches import S1, SCRIPT

    learner = await create_learner(pg_db)

    def new(e: Any, seq: int, **payload: Any) -> NewEvent:
        return _new(e.type, e.payload | payload, f"k{seq}", domain_id=e.domain_id,
                    session_id=e.session_id)  # fmt: skip

    answer, verdict = SCRIPT[11], SCRIPT[12]  # seq 12 and 13 of the script
    events = [new(e, e.seq) for e in SCRIPT[:10]]
    events += [new(answer, 11), new(verdict, 12, answer_seq=11)]
    await append_events(pg_db, learner, events)
    reader = Neo4jGraphReader(neo4j, settings, learner_id=learner, db=pg_db)
    before = await reader.state_at(learner, 11, [UUID(S1)])
    after = await reader.state_at(learner, 12, [UUID(S1)])
    assert before.skills[0].levels[2].status == "not_tested"
    assert after.skills[0].levels[2].status == "proven"


async def test_disputes_check_the_target_and_append_one_event(
    pg_db: Db, neo4j: AsyncDriver, settings: Settings
) -> None:
    """WP8.1 (`Т-§2.8`, D-A-192): a dispute of the learner's evidence or verdict and a typo are
    one event each; another learner's target is «not found»; a typo is keyed by its verdict."""
    from quack.domains.disputes import DisputeRequest, declare_typo, file_dispute

    mine, other = await create_learner(pg_db), await create_learner(pg_db)
    evidence = str(uuid4())
    async with neo4j.session() as session:
        await session.run("CREATE (:Evidence {id: $e, learnerId: $l})", e=evidence, l=str(mine))
    answer = _new("answer.submitted", {"task_id": str(uuid4()), "source": "chat",
                  "answer": {"kind": "number", "value": "2"}}, "a")  # fmt: skip
    await append_events(pg_db, mine, [answer])

    def ask(kind: str, target: str) -> DisputeRequest:
        return DisputeRequest(target_kind=kind, target_id=target, idempotency_key=target)  # type: ignore[arg-type]

    assert await file_dispute(pg_db, neo4j, None, mine, ask("evidence", evidence)) == 2
    assert await file_dispute(pg_db, neo4j, None, other, ask("evidence", evidence)) is None
    assert await file_dispute(pg_db, neo4j, None, mine, ask("verdict", "1:main")) == 3
    assert await file_dispute(pg_db, neo4j, None, other, ask("verdict", "1:main")) is None
    assert await declare_typo(pg_db, None, mine, 1, "main") == 4
    assert await declare_typo(pg_db, None, mine, 1, "main") == 4  # the same verdict, one event
    assert await declare_typo(pg_db, None, other, 1, "main") is None


async def test_topic_edits_check_the_topic_and_append_one_event(
    pg_db: Db, neo4j: AsyncDriver, settings: Settings
) -> None:
    """WP8.2 (`Т-§4.11`, D-A-193): each edit of the learner's topic is one event; a topic of
    another learner or of another domain is «not found»; a retry gives the same event."""
    from quack.domains import topic_edits as edits

    mine, other = await create_learner(pg_db), await create_learner(pg_db)
    t1, t2, far = uuid4(), uuid4(), uuid4()
    async with neo4j.session() as session:
        await session.run(
            "UNWIND $rows AS r CREATE (:Topic {id: r.id, learnerId: $l, name: r.name, "
            "domainId: r.d, knownClaimedAtMs: 0})",
            l=str(mine),
            rows=[
                {"id": str(t1), "name": "a", "d": "d"},
                {"id": str(t2), "name": "b", "d": "d"},
                {"id": str(far), "name": "c", "d": "e"},
            ],
        )
    assert await edits.rename(pg_db, neo4j, None, mine, t1, "A") == 1
    assert await edits.rename(pg_db, neo4j, None, mine, t1, "A") == 1  # a retry
    assert await edits.rename(pg_db, neo4j, None, other, t1, "A") is None
    assert await edits.merge(pg_db, neo4j, None, mine, t1, far) is None  # another domain
    assert await edits.merge(pg_db, neo4j, None, mine, t1, t2) == 2
    assert await edits.hide(pg_db, neo4j, None, mine, t2) == 3
    assert await edits.claim_known(pg_db, neo4j, None, mine, t2) == 4
    assert await edits.reassign(pg_db, neo4j, None, mine, 99, t2) is None  # no such episode
