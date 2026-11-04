"""Phase 3 `graph.curate` on the Phase 3 job pipeline (ТЗ Фазы 3 §2.5, §4, §5): presence
deferral, promotion, normName deduplication and the `curator@1` pass.

Moved from `tests/domains/test_diagnostic_and_graph_view.py` with the handler (D-A-208): the
file's other tests checked the removed diagnostic and the Phase 3 map of a domain.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from neo4j import AsyncDriver
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from quack.config import Settings
from quack.db.postgres import SessionFactory
from quack.db.redis import presence_key
from quack.domains.schemas import CuratorMerge, CuratorOutput
from quack.events.append import append_events
from quack.events.models import NewEvent
from quack.events.payloads import PrereqEdge, SkillDepEdge, SkillDraft, TopicDraft
from quack.events.reader import read_learner_events
from quack.graph.ids import deterministic_id
from quack.graph.neo4j_store import Neo4jGraphStore
from quack.graph.worker import ProjectorWorker
from quack.jobs import kinds
from quack.jobs.curation_p3 import handle_graph_curate
from quack.jobs.queue import claim_next_job, complete_job, enqueue_job
from quack.jobs.runner import JobRunner
from tests.support.llm import FakeLLMProvider
from tests.support.resources import build_job_context


@pytest.fixture
def fake_llm_provider() -> FakeLLMProvider:
    return FakeLLMProvider()


async def _seed_linear_dag_domain(
    db: SessionFactory,
    settings: Settings,
    pg_engine: AsyncEngine,
    neo4j: AsyncDriver,
    redis: Redis,
    learner_id: UUID,
) -> tuple[UUID, tuple[UUID, UUID, UUID], tuple[UUID, UUID, UUID]]:
    """Seed an active domain with chain `T1 -> PREREQ_OF -> T2 -> PREREQ_OF -> T3` and
    `S2 -> DEPENDS_ON -> S1`, `S3 -> DEPENDS_ON -> S2` directly via `append_events` and
    project it into Neo4j via `ProjectorWorker`.
    """
    domain_id = uuid4()
    t1_id, t2_id, t3_id = uuid4(), uuid4(), uuid4()
    s1_id, s2_id, s3_id = uuid4(), uuid4(), uuid4()

    topics = [
        TopicDraft(topic_id=t1_id, name="T1 Basics", description="Foundational topic"),
        TopicDraft(topic_id=t2_id, name="T2 Core Hub", description="Middle hub topic"),
        TopicDraft(topic_id=t3_id, name="T3 Advanced", description="Advanced dependent topic"),
    ]
    skills = [
        SkillDraft(skill_id=s1_id, topic_id=t1_id, name="S1 Basic Skill"),
        SkillDraft(skill_id=s2_id, topic_id=t2_id, name="S2 Hub Skill"),
        SkillDraft(skill_id=s3_id, topic_id=t3_id, name="S3 Advanced Skill"),
    ]
    prereqs = [
        PrereqEdge(from_topic_id=t1_id, to_topic_id=t2_id),
        PrereqEdge(from_topic_id=t2_id, to_topic_id=t3_id),
    ]
    skill_deps = [
        SkillDepEdge(skill_id=s2_id, depends_on_skill_id=s1_id),
        SkillDepEdge(skill_id=s3_id, depends_on_skill_id=s2_id),
    ]

    async with db() as session, session.begin():
        await append_events(
            session,
            learner_id,
            [
                NewEvent(
                    type="domain.created",
                    actor="learner",
                    domain_id=domain_id,
                    idempotency_key=f"seed-domain:{domain_id}",
                    payload={
                        "domain_id": str(domain_id),
                        "name": "Linear Algebra",
                        "slug": f"linalg-{domain_id.hex[:6]}",
                        "has_materials": False,
                    },
                ),
                NewEvent(
                    type="structure.proposed",
                    actor="structurer@1",
                    domain_id=domain_id,
                    idempotency_key=f"seed-propose:{domain_id}",
                    payload={
                        "domain_id": str(domain_id),
                        "structure_version": 1,
                        "topics": [t.model_dump(mode="json") for t in topics],
                        "skills": [s.model_dump(mode="json") for s in skills],
                        "prereqs": [e.model_dump(mode="json") for e in prereqs],
                        "skill_deps": [d.model_dump(mode="json") for d in skill_deps],
                        "misconceptions": [],
                    },
                ),
                NewEvent(
                    type="structure.confirmed",
                    actor="learner",
                    domain_id=domain_id,
                    idempotency_key=f"seed-confirm:{domain_id}",
                    payload={
                        "domain_id": str(domain_id),
                        "structure_version": 1,
                    },
                ),
            ],
            publish_wakeup=False,
        )

    worker = ProjectorWorker(settings, pg_engine, db, neo4j, redis)
    await worker.run_once()
    return domain_id, (t1_id, t2_id, t3_id), (s1_id, s2_id, s3_id)


async def test_graph_curate_defers_when_learner_presence_active(
    seeded_learner: tuple[UUID, str],
    fake_llm_provider: FakeLLMProvider,
    db: SessionFactory,
    settings: Settings,
    pg_engine: AsyncEngine,
    neo4j: AsyncDriver,
    redis: Redis,
) -> None:
    """4. `graph.curate` worker checks `presence:learner:{id}` in Redis: when present, does not
    merge or call LLM and defers the job in `ops.jobs` by ~10 minutes (ТЗ §2.5, §5).
    """
    learner_id, _ = seeded_learner
    domain_id, _, _ = await _seed_linear_dag_domain(
        db, settings, pg_engine, neo4j, redis, learner_id
    )

    await redis.set(presence_key(learner_id), "active-session", ex=300)

    async with db() as session, session.begin():
        events_before = await read_learner_events(session, learner_id)
        job_id = await enqueue_job(
            session,
            kinds.graph_curate(
                learner_id, domain_id, {"domain_id": str(domain_id)}, required_seq=None
            ),
        )

    before_run = datetime.now(UTC)
    runner = JobRunner(
        settings,
        db,
        "test-worker",
        handlers={"graph.curate": handle_graph_curate},
        context=build_job_context(settings, db, neo4j, redis, provider=fake_llm_provider),
    )
    assert await runner.run_one()

    # Verify LLM was not called and no curation events were emitted.
    assert fake_llm_provider.calls == []
    async with db() as session:
        events_after = await read_learner_events(session, learner_id)
        row = (
            await session.execute(
                text("SELECT status, run_after, attempt FROM ops.jobs WHERE id = :id"),
                {"id": job_id},
            )
        ).one()

    assert len(events_after) == len(events_before)
    assert row[0] == "queued" and row[2] == 0
    assert row[1] >= before_run + timedelta(minutes=9, seconds=30)


async def test_graph_curate_deterministic_promotion_dedup_and_curator_model_pass(
    seeded_learner: tuple[UUID, str],
    fake_llm_provider: FakeLLMProvider,
    db: SessionFactory,
    settings: Settings,
    pg_engine: AsyncEngine,
    neo4j: AsyncDriver,
    redis: Redis,
) -> None:
    """5. `graph.curate` without active presence:
    - promotes provisional skill with `evidenceCount >= 2` (`skill.promoted`),
    - deduplicates provisional skill matching `normName` of an `active` skill (`skill.merged`
      with `source_skill_id = provisional`, `target_skill_id = active`, creating `Alias`),
    - runs `curator@1` for non-trivial merges (`actor="curator@1"`) while filtering out topic
      merges that would create a cycle in `PREREQ_OF` (ТЗ §2.5, §4, §5).
    """
    learner_id, _ = seeded_learner
    domain_id, (t1_id, _t2_id, t3_id), (s1_id, _s2_id, _s3_id) = await _seed_linear_dag_domain(
        db, settings, pg_engine, neo4j, redis, learner_id
    )

    session_id = uuid4()
    turn_id = uuid4()
    s_active_dup_id = uuid4()

    # Seed provisional skills via turn.extracted and then add an active skill sharing normName.
    async with db() as session, session.begin():
        stored = await append_events(
            session,
            learner_id,
            [
                NewEvent(
                    type="turn.extracted",
                    actor="extractor@1",
                    domain_id=domain_id,
                    session_id=session_id,
                    turn_id=turn_id,
                    idempotency_key=f"extract:{turn_id}",
                    payload={
                        "session_id": str(session_id),
                        "turn_id": str(turn_id),
                        "observations": [
                            {
                                "skill": {
                                    "new_skill": {
                                        "name": "LU Decomposition",
                                        "topic_id": str(t1_id),
                                    }
                                },
                                "direction": "positive",
                                "strength": 0.9,
                                "independence": 1.0,
                                "tested_depth": 0.6,
                                "polarity_weight": 1.0,
                                "evidence_text": "Factored A = LU",
                            },
                            {
                                "skill": {
                                    "new_skill": {
                                        "name": "LU Decomposition",
                                        "topic_id": str(t1_id),
                                    }
                                },
                                "direction": "positive",
                                "strength": 0.85,
                                "independence": 1.0,
                                "tested_depth": 0.7,
                                "polarity_weight": 1.0,
                                "evidence_text": "Used LU for system solve",
                            },
                            {
                                "skill": {
                                    "new_skill": {
                                        "name": "Matrix Trace",
                                        "topic_id": str(t1_id),
                                    }
                                },
                                "direction": "positive",
                                "strength": 0.8,
                                "independence": 1.0,
                                "tested_depth": 0.5,
                                "polarity_weight": 1.0,
                                "evidence_text": "Summed diagonal entries",
                            },
                            {
                                "skill": {
                                    "new_skill": {
                                        "name": "Row Echelon Reduction",
                                        "topic_id": str(t1_id),
                                    }
                                },
                                "direction": "positive",
                                "strength": 0.75,
                                "independence": 1.0,
                                "tested_depth": 0.5,
                                "polarity_weight": 1.0,
                                "evidence_text": "Reduced matrix to echelon form",
                            },
                        ],
                        "misconceptions": [],
                    },
                ),
                NewEvent(
                    type="structure.edited",
                    actor="learner",
                    domain_id=domain_id,
                    idempotency_key=f"edit-dup:{domain_id}",
                    payload={
                        "domain_id": str(domain_id),
                        "structure_version": 2,
                        "added_skills": [
                            SkillDraft(
                                skill_id=s_active_dup_id,
                                topic_id=t1_id,
                                name="Matrix Trace",
                                description="Canonical active trace skill",
                            ).model_dump(mode="json")
                        ],
                    },
                ),
            ],
            publish_wakeup=False,
        )

    extract_seq = stored[0].seq
    s_prov_promote_id = UUID(deterministic_id(learner_id, extract_seq, "skill:0"))
    s_prov_dup_id = UUID(deterministic_id(learner_id, extract_seq, "skill:2"))
    s_prov_llm_id = UUID(deterministic_id(learner_id, extract_seq, "skill:3"))

    worker = ProjectorWorker(settings, pg_engine, db, neo4j, redis)
    await worker.run_once()

    # Queue curator@1 output: valid merge s_prov_llm -> s1_id, plus invalid cycle topic merge.
    fake_llm_provider.enqueue(
        CuratorOutput(
            promotions=[],
            skill_merges=[
                CuratorMerge(
                    source_id=s_prov_llm_id,
                    target_id=s1_id,
                    reason="Equivalent row reduction skill",
                )
            ],
            topic_merges=[
                CuratorMerge(
                    source_id=t3_id,
                    target_id=t1_id,
                    reason="Invalid merge creating cycle T1 -> T2 -> T1",
                )
            ],
            misconception_merges=[],
        )
    )

    async with db() as session, session.begin():
        await enqueue_job(
            session,
            kinds.graph_curate(
                learner_id, domain_id, {"domain_id": str(domain_id)}, required_seq=None
            ),
        )
    async with db() as session, session.begin():
        claimed = await claim_next_job(session, "test-worker", ["graph.curate"])
    assert claimed is not None

    ctx = build_job_context(settings, db, neo4j, redis, provider=fake_llm_provider)
    await handle_graph_curate(claimed, ctx)
    async with db() as session, session.begin():
        await complete_job(session, claimed.id, "test-worker")

    await worker.run_once()

    async with db() as session:
        all_events = await read_learner_events(session, learner_id)

    promoted_events = [e for e in all_events if e.type == "skill.promoted"]
    merged_skill_events = [e for e in all_events if e.type == "skill.merged"]
    merged_topic_events = [e for e in all_events if e.type == "topic.merged"]

    assert any(UUID(e.payload["skill_id"]) == s_prov_promote_id for e in promoted_events)
    assert any(
        UUID(e.payload["source_skill_id"]) == s_prov_dup_id
        and UUID(e.payload["target_skill_id"]) == s_active_dup_id
        for e in merged_skill_events
    )
    assert any(
        UUID(e.payload["source_skill_id"]) == s_prov_llm_id
        and UUID(e.payload["target_skill_id"]) == s1_id
        and e.actor == "curator@1"
        for e in merged_skill_events
    )
    assert merged_topic_events == []

    # Verify Neo4j state after projection: promoted skill is active, merged skill has Alias.
    graph = await Neo4jGraphStore(neo4j, str(learner_id)).dump()
    promoted_props = graph.get("Skill", str(s_prov_promote_id))
    assert promoted_props is not None
    assert promoted_props["status"] == "active"

    dup_props = graph.get("Skill", str(s_prov_dup_id))
    assert dup_props is not None
    assert dup_props["status"] == "merged"

    alias_props = graph.get("Alias", str(s_prov_dup_id))
    assert alias_props is not None
    assert alias_props["targetId"] == str(s_active_dup_id)
