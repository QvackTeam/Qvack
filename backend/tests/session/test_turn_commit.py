"""ТЗ Ф4 §8.9 T-TT7 and §8.x T-EV4 (stream B part): `turn.committed` with the events the turn
produced (`task.created`, `agent.requested`, `hub.deadline_set`) — one `append_events` call —
and the `ops.turn_manifests` row in the same transaction; a failure before the end writes
nothing; a repeat writes nothing new (law 5). Labels are translated to ids by code before the
write (Т-§4.5, WP13.3); an unknown label writes nothing."""

from __future__ import annotations

from dataclasses import replace
from typing import Any
from uuid import UUID, uuid4

import pytest

from quack.config import Settings
from quack.db.db import Db
from quack.events import records
from quack.events.values import AnswerSpec, MathValue
from quack.llm.labels import LabelMap, UnknownLabelError
from quack.llm.streaming import StreamUsage
from quack.practice.role_outputs import TaskCondition
from quack.practice.task_store import create_task, get_task
from quack.session.teacher_output import TeacherOutputV2
from quack.session.turn_commit import TurnManifestRow, commit_turn, turn_batch
from quack.session.turn_graph import TurnToCommit
from tests.db.fixtures import create_learner

SETTINGS = Settings()
SKILL, TOPIC, HUB, MISCONCEPTION = uuid4(), uuid4(), uuid4(), uuid4()
NUMBER = {"type": "number", "value": {"latex": "\\frac{1}{3}", "sympy": "1/3"}}
TEXT = "Every term is a third of the one before it."


def _labels() -> LabelMap:
    return LabelMap.build(
        SETTINGS, skills=[SKILL], topics=[TOPIC], hubs=[HUB], misconceptions=[MISCONCEPTION]
    )


def _output(**markup: Any) -> TeacherOutputV2:
    base: dict[str, Any] = {
        "tasks": [
            {
                "element_id": "e1",
                "tests": [{"skill": "S1", "level": 3}],
                "methodNamed": False,
                "answer": NUMBER,
            }
        ],
        "elements": [
            {
                "element_id": "e1",
                "kind": "short_answer",
                "prompt": "What is the sum?",
                "ask_confidence": False,
            }
        ],
        "exposures": [{"skill": "S1", "kind": "explained", "approach": "none"}],
        "targetsMisconception": "M1",
        "planUpdate": {
            "completed_steps": ["definition"],
            "current_step": "sum of a geometric series",
            "next_steps": [],
            "branches": [],
            "cancel_requests": [],
        },
        "agentRequests": [
            {
                "kind": "viz",
                "params": {
                    "skill": "S1",
                    "level": None,
                    "topic": None,
                    "task": None,
                    "misconception": None,
                    "description": "partial sums on a number line",
                },
                "needed_in_session": True,
            }
        ],
        "correctionsAcknowledged": [],
        "decisionReason": "practice after the explanation",
        "deadline": {
            "hub_label": "H1",
            "new_hub_name": None,
            "deadline_at": "2026-12-01T09:00:00+00:00",
            "coverage": ["T1"],
        },
    }
    return TeacherOutputV2.model_validate(
        {
            "p1_head": {
                "intent": "explain",
                "targetSkills": ["S1"],
                "verdict_stance": None,
                "branchType": None,
                "approach": "example_first",
            },
            "p2_body": {
                "blocks": [
                    {"block_id": "b1", "text": TEXT, "element_id": None},
                    {"block_id": "b2", "text": None, "element_id": "e1"},
                ]
            },
            "p3_markup": {**base, **markup},
        }
    )


def _turn(output: TeacherOutputV2 | None = None) -> TurnToCommit:
    return TurnToCommit(
        output=output or _output(),
        text=TEXT,
        role="teacher",
        model="muse-wonder-1.0",
        effort="low",
        degraded_mode=None,
        guard_retries=1,
        usage=StreamUsage(input_tokens=100, output_tokens=40),
    )


def _manifest(learner_id: UUID, session_id: UUID, labels: LabelMap) -> TurnManifestRow:
    return TurnManifestRow(
        manifest_id=uuid4(),
        learner_id=learner_id,
        session_id=session_id,
        prompt_version="teacher@2",
        doctrine_version=None,
        renderer_version="renderer@1",
        role="teacher",
        model="muse-wonder-1.0",
        effort="low",
        projected_seq=0,
        overlay_seqs=[1],
        label_table=labels.table(),
        degraded_mode=None,
    )


async def _events(db: Db, learner_id: UUID) -> list[dict[str, Any]]:
    return await db.fetch_all(
        "SELECT seq, type, payload, idempotency_key FROM core.events "
        "WHERE learner_id = %(l)s ORDER BY seq",
        {"l": learner_id},
    )


async def _manifests(db: Db, learner_id: UUID) -> list[dict[str, Any]]:
    return await db.fetch_all(
        "SELECT * FROM ops.turn_manifests WHERE learner_id = %(l)s", {"l": learner_id}
    )


def _batch(learner_id: UUID, output: TeacherOutputV2 | None = None) -> Any:
    labels = _labels()
    session_id = uuid4()
    return turn_batch(
        _turn(output),
        labels,
        manifest=_manifest(learner_id, session_id, labels),
        action_seq=1,
        domain_id=None,
    )


async def test_turn_atomic_and_manifest(pg_db: Db) -> None:
    learner_id = await create_learner(pg_db)
    batch = _batch(learner_id)

    seq = await commit_turn(pg_db, batch, learner_id=learner_id)

    events = await _events(pg_db, learner_id)
    assert [e["type"] for e in events] == [
        "task.created",
        "turn.committed",
        "agent.requested",
        "hub.deadline_set",
    ]
    assert [e["seq"] for e in events] == [seq - 1, seq, seq + 1, seq + 2]
    turn = events[1]["payload"]
    assert turn["action_seq"] == 1 and turn["text"] == TEXT and turn["guard_retries"] == 1
    assert turn["head"]["target_skill_ids"] == [str(SKILL)]
    assert turn["markup"]["exposures"][0]["skill_id"] == str(SKILL)
    assert turn["markup"]["targets_misconception_id"] == str(MISCONCEPTION)
    [task] = turn["markup"]["tasks"]
    assert task["tests"] == [{"skill_id": str(SKILL), "new_skill": None, "level": 3}]
    assert events[0]["payload"]["task_id"] == task["task_id"]
    assert events[0]["payload"]["source"] == "teacher"
    assert await get_task(pg_db, learner_id=learner_id, task_id=UUID(task["task_id"]))
    request = events[2]["payload"]
    assert request["params"]["skill_id"] == str(SKILL) and request["needed_in_session"]
    assert turn["markup"]["agent_requests"][0]["request_id"] == request["request_id"]
    deadline = events[3]["payload"]
    assert deadline["hub_id"] == str(HUB) and deadline["source"] == "turn"
    assert turn["markup"]["deadline"]["coverage_topic_ids"] == [str(TOPIC)]

    [manifest] = await _manifests(pg_db, learner_id)
    assert manifest["manifest_id"] == batch.manifest.manifest_id
    assert str(manifest["manifest_id"]) == turn["manifest_id"]
    assert manifest["prompt_version"] == "teacher@2" and manifest["effort"] == "low"
    assert manifest["label_table"]["S1"] == str(SKILL)


async def test_failure_before_the_end_writes_nothing(pg_db: Db) -> None:
    """The task document cannot be stored (its id is taken) → no event, no manifest."""
    learner_id, other = await create_learner(pg_db), await create_learner(pg_db)
    batch = _batch(learner_id)
    [new_task] = batch.tasks
    await create_task(
        pg_db,
        learner_id=other,
        task_id=new_task.task_id,
        family_id=new_task.task_id,
        source="teacher",
        condition=TaskCondition(text="taken", latex=None),
        markup=records.TaskMarkupRecord(
            tests=[records.TestedLevelRecord(skill_id=SKILL, level=3)],
            method_named=False,
            answer=AnswerSpec(type="number", value=MathValue(latex="1", sympy="1")),
        ),
        verification="unchecked",
        actor="teacher@2",
        idempotency_key=f"task:{new_task.task_id}",
    )

    with pytest.raises(Exception):  # noqa: B017 — the unique violation of the store
        await commit_turn(pg_db, batch, learner_id=learner_id)

    assert await _events(pg_db, learner_id) == []
    assert await _manifests(pg_db, learner_id) == []


async def test_manifest_failure_writes_no_turn(pg_db: Db) -> None:
    """The manifest row cannot be stored (`prompt_version` NOT NULL) → no turn, no task."""
    learner_id = await create_learner(pg_db)
    batch = _batch(learner_id)
    broken = replace(batch, manifest=replace(batch.manifest, prompt_version=None))

    with pytest.raises(Exception):  # noqa: B017 — the NOT NULL violation of the store
        await commit_turn(pg_db, broken, learner_id=learner_id)

    assert await _events(pg_db, learner_id) == []
    [new_task] = batch.tasks
    assert await get_task(pg_db, learner_id=learner_id, task_id=new_task.task_id) is None


async def test_repeat_writes_nothing_new(pg_db: Db) -> None:
    learner_id = await create_learner(pg_db)
    batch = _batch(learner_id)

    first = await commit_turn(pg_db, batch, learner_id=learner_id)
    second = await commit_turn(pg_db, batch, learner_id=learner_id)

    assert first == second
    assert len(await _events(pg_db, learner_id)) == 4
    assert len(await _manifests(pg_db, learner_id)) == 1


async def test_unknown_label_writes_nothing(pg_db: Db) -> None:
    learner_id = await create_learner(pg_db)
    bad = _output(
        deadline={
            "hub_label": "H1",
            "new_hub_name": None,
            "deadline_at": "2026-12-01T09:00:00+00:00",
            "coverage": ["T7"],
        }
    )

    with pytest.raises(UnknownLabelError):
        await commit_turn(pg_db, _batch(learner_id, bad), learner_id=learner_id)

    assert await _events(pg_db, learner_id) == []
    assert await _manifests(pg_db, learner_id) == []


def test_turn_without_side_effects_is_one_event() -> None:
    output = _output(tasks=[], elements=[], agentRequests=[], deadline=None)
    output = output.model_copy(
        update={
            "p2_body": output.p2_body.model_copy(
                update={"blocks": [b for b in output.p2_body.blocks if b.text is not None]}
            )
        }
    )
    batch = _batch(uuid4(), output)

    assert [e.type for e in batch.events] == ["turn.committed"]
    assert batch.tasks == []
