"""The write of a teacher turn (Т-§2.2, Т-§3.2, Т-§4.5; ТЗ Ф4 WP2.2, WP13.3, WP13.9).

`turn_batch` translates the labels of the turn output to ids (an unknown label —
`UnknownLabelError`, nothing is written) and builds the batch: `task.created` of the tasks
the turn shows, `turn.committed`, `agent.requested` of its requests, `hub.deadline_set` of a
deadline heard in the conversation (D-B-149). `commit_turn` writes the batch with one
`append_events` call, the documents of the new tasks and the `ops.turn_manifests` row in one
transaction: a failure writes none of them; a repeat of the same batch writes nothing new.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from psycopg.types.json import Jsonb
from pydantic import TypeAdapter
from redis.asyncio import Redis

from quack.db.db import Db
from quack.events import records
from quack.events.event_types import (
    AgentRequested,
    DegradedMode,
    HubDeadlineSet,
    TurnCommitted,
)
from quack.events.log import NewEvent, append_events
from quack.events.values import AnswerSpec
from quack.llm.labels import LabelMap
from quack.logging import get_logger
from quack.practice.markup import TaskMarkup, TestedLevel
from quack.practice.role_outputs import TaskCondition
from quack.practice.task_store import get_task, insert_task_document, task_created_event
from quack.session.elements import Element
from quack.session.teacher_output import AgentRequest, TurnMarkup
from quack.session.turn_graph import TurnToCommit

log = get_logger(__name__)

_ELEMENT_RECORD: TypeAdapter[records.ElementRecord] = TypeAdapter(records.ElementRecord)

_INSERT_MANIFEST = """
INSERT INTO ops.turn_manifests (
    manifest_id, learner_id, session_id, prompt_version, doctrine_version, renderer_version,
    role, model, effort, projected_seq, overlay_seqs, label_table, digest_id, chunk_ids,
    similar_ids, context_text, degraded_mode
) VALUES (
    %(manifest_id)s, %(learner_id)s, %(session_id)s, %(prompt_version)s, %(doctrine_version)s,
    %(renderer_version)s, %(role)s, %(model)s, %(effort)s, %(projected_seq)s,
    %(overlay_seqs)s, %(label_table)s, %(digest_id)s, %(chunk_ids)s, %(similar_ids)s,
    %(context_text)s, %(degraded_mode)s
)
ON CONFLICT (manifest_id) DO NOTHING
"""


@dataclass(frozen=True)
class TurnManifestRow:
    """A row of `ops.turn_manifests` (Т-§3.2, Т-§10.6, WP13.9); `context_text` — only for the
    `turn_context_sample_rate` sample."""

    manifest_id: UUID
    learner_id: UUID
    session_id: UUID
    prompt_version: str
    doctrine_version: str | None
    renderer_version: str | None
    role: str
    model: str
    effort: str | None
    projected_seq: int
    overlay_seqs: list[int] = field(default_factory=list)
    label_table: dict[str, str] = field(default_factory=dict)
    digest_id: UUID | None = None
    chunk_ids: list[UUID] = field(default_factory=list)
    similar_ids: list[UUID] = field(default_factory=list)
    context_text: str | None = None
    degraded_mode: DegradedMode | None = None


@dataclass(frozen=True)
class NewTurnTask:
    """The document of a task the turn shows (`content.tasks`), stored with its
    `task.created` (`idempotency_key`)."""

    task_id: UUID
    condition: TaskCondition
    answer_spec: AnswerSpec
    idempotency_key: str


@dataclass(frozen=True)
class TurnBatch:
    events: list[NewEvent]
    tasks: list[NewTurnTask]
    manifest: TurnManifestRow
    domain_id: UUID | None


def turn_batch(
    turn: TurnToCommit,
    labels: LabelMap,
    *,
    manifest: TurnManifestRow,
    action_seq: int,
    domain_id: UUID | None,
) -> TurnBatch:
    """The events of the turn with ids instead of labels (WP2.2, WP13.3)."""
    output = turn.output
    key = f"turn:{manifest.manifest_id}"
    common: dict[str, Any] = {
        "actor": manifest.prompt_version,
        "domain_id": domain_id,
        "session_id": manifest.session_id,
        "causation_seq": action_seq,
    }
    elements = {e.element_id: e for e in output.p3_markup.elements}
    tasks: list[NewTurnTask] = []
    task_events: list[NewEvent] = []
    task_records: list[records.TurnTaskRecord] = []
    for task in output.p3_markup.tasks:
        task_id = uuid4()
        markup = markup_record(task, labels)
        task_key = f"{key}:task:{task.element_id}"
        task_records.append(
            records.TurnTaskRecord(
                **markup.model_dump(), element_id=task.element_id, task_id=task_id
            )
        )
        # D-B-149: a task of the turn is its own family; its condition is the element text.
        task_events.append(
            task_created_event(
                task_id=task_id,
                family_id=task_id,
                source="teacher",
                markup=markup,
                verification="unchecked",
                idempotency_key=task_key,
                **common,
            )
        )
        tasks.append(
            NewTurnTask(
                task_id=task_id,
                condition=TaskCondition(text=_condition(elements.get(task.element_id)), latex=None),
                answer_spec=markup.answer,
                idempotency_key=task_key,
            )
        )
    requests = [_request_record(r, labels) for r in output.p3_markup.agent_requests]
    markup = _turn_markup(output.p3_markup, labels, task_records, requests)
    head = output.p1_head
    committed = TurnCommitted(
        action_seq=action_seq,
        text=turn.text,
        blocks=[records.BodyBlockRecord(**b.model_dump()) for b in output.p2_body.blocks],
        head=records.TurnHeadRecord(
            intent=head.intent,
            target_skill_ids=[labels.resolve("skill", s) for s in head.target_skills],
            verdict_stance=head.verdict_stance,
            branch_type=head.branch_type,
            approach=head.approach,
        ),
        markup=markup,
        role=turn.role,
        model=turn.model,
        effort=turn.effort,
        degraded_mode=turn.degraded_mode,
        guard_retries=turn.guard_retries,
        manifest_id=manifest.manifest_id,
    )
    events = [
        *task_events,
        NewEvent(type="turn.committed", payload=committed, idempotency_key=key, **common),
    ]
    for index, request in enumerate(requests):
        payload = AgentRequested(**request.model_dump())
        events.append(
            NewEvent(
                type="agent.requested",
                payload=payload,
                idempotency_key=f"{key}:agent:{index}",
                **common,
            )
        )
    deadline = markup.deadline
    if deadline is not None and deadline.hub_id is not None:
        events.append(
            NewEvent(
                type="hub.deadline_set",
                payload=HubDeadlineSet(
                    hub_id=deadline.hub_id,
                    deadline_at_ms=deadline.deadline_at_ms,
                    source="turn",
                ),
                idempotency_key=f"{key}:deadline",
                **common,
            )
        )
    elif deadline is not None:
        # D-B-149 [ПРОВЕРИТЬ]: a new hub needs `hub.created` fields the markup has no
        # values for (`kind`, `origin`, `control_type`); kept in the turn markup only.
        log.warning("turn_deadline_new_hub_not_written", new_hub_name=deadline.new_hub_name)
    return TurnBatch(events=events, tasks=tasks, manifest=manifest, domain_id=domain_id)


async def commit_turn(
    db: Db, batch: TurnBatch, *, learner_id: UUID, redis: Redis | None = None
) -> int:
    """Write the batch, the task documents and the manifest row in one transaction; the seq
    of `turn.committed`."""
    manifest = batch.manifest
    if manifest.learner_id != learner_id:
        raise ValueError("the manifest belongs to another learner")
    async with db.transaction():
        stored = await append_events(db, learner_id, batch.events, redis=redis)
        by_key = {event.idempotency_key: event for event in stored}
        for task in batch.tasks:
            if await get_task(db, learner_id=learner_id, task_id=task.task_id):
                continue
            await insert_task_document(
                db,
                learner_id=learner_id,
                task_id=task.task_id,
                domain_id=batch.domain_id,
                source="teacher",
                condition=task.condition,
                answer_spec=task.answer_spec,
                created_seq=by_key[task.idempotency_key].seq,
            )
        await db.execute(_INSERT_MANIFEST, _manifest_params(manifest))
    [turn] = [event for event in stored if event.type == "turn.committed"]
    return turn.seq


# --- labels → ids (Т-§4.5) ---


def markup_record(markup: TaskMarkup, labels: LabelMap) -> records.TaskMarkupRecord:
    """Т-§5.2 markup with ids: skills, misconceptions of the options, tasks of `variantOf` and
    `pairTaskId`."""
    return records.TaskMarkupRecord(
        tests=[_tested(t, labels) for t in markup.tests],
        method_named=markup.method_named,
        variant_of=_optional(labels, "task", markup.variant_of),
        answer=markup.answer,
        options=None
        if markup.options is None
        else [
            records.OptionTrapRecord(
                option_id=o.option_id,
                misconception_id=_optional(labels, "misconception", o.misconception),
                hypothesis=o.hypothesis,
                neighbor_idea=o.neighbor_idea,
            )
            for o in markup.options
        ],
        pair_task_id=_optional(labels, "task", markup.pair_task_id),
        form=markup.form,
        parts=None
        if markup.parts is None
        else [
            records.TaskPartRecord(
                part=p.part,
                answer=p.answer,
                tests=None if p.tests is None else [_tested(t, labels) for t in p.tests],
            )
            for p in markup.parts
        ],
    )


def _tested(tested: TestedLevel, labels: LabelMap) -> records.TestedLevelRecord:
    return records.TestedLevelRecord(
        skill_id=_optional(labels, "skill", tested.skill),
        new_skill=tested.new_skill,
        level=tested.level,
    )


def _optional(labels: LabelMap, kind: Any, label: str | None) -> UUID | None:
    return None if label is None else labels.resolve(kind, label)


def _request_record(request: AgentRequest, labels: LabelMap) -> records.AgentRequestRecord:
    params = request.params
    return records.AgentRequestRecord(
        request_id=uuid4(),
        kind=request.kind,
        params=records.AgentParamsRecord(
            skill_id=_optional(labels, "skill", params.skill),
            level=params.level,
            topic_id=_optional(labels, "topic", params.topic),
            task_id=_optional(labels, "task", params.task),
            misconception_id=_optional(labels, "misconception", params.misconception),
            description=params.description,
        ),
        needed_in_session=request.needed_in_session,
    )


def _turn_markup(
    markup: TurnMarkup,
    labels: LabelMap,
    tasks: list[records.TurnTaskRecord],
    requests: list[records.AgentRequestRecord],
) -> records.TurnMarkupRecord:
    plan = markup.plan_update
    deadline = markup.deadline
    return records.TurnMarkupRecord(
        tasks=tasks,
        elements=[_element_record(e, labels) for e in markup.elements],
        exposures=[
            records.ExposureRecord(
                skill_id=labels.resolve("skill", e.skill), kind=e.kind, approach=e.approach
            )
            for e in markup.exposures
        ],
        targets_misconception_id=_optional(labels, "misconception", markup.targets_misconception),
        plan_update=records.PlanUpdateRecord(
            completed_steps=plan.completed_steps,
            current_step=plan.current_step,
            next_steps=plan.next_steps,
            branches=[records.BranchRecord(**b.model_dump()) for b in plan.branches],
            cancel_request_ids=[labels.resolve("request", r) for r in plan.cancel_requests],
        ),
        agent_requests=requests,
        corrections_acknowledged=markup.corrections_acknowledged,
        decision_reason=markup.decision_reason,
        deadline=None
        if deadline is None
        else records.DeadlineRecord(
            hub_id=_optional(labels, "hub", deadline.hub_label),
            new_hub_name=deadline.new_hub_name,
            deadline_at_ms=int(datetime.fromisoformat(deadline.deadline_at).timestamp() * 1000),
            coverage_topic_ids=[labels.resolve("topic", t) for t in deadline.coverage],
        ),
    )


def _element_record(element: Element, labels: LabelMap) -> records.ElementRecord:
    data = element.model_dump(mode="json")
    if element.kind == "card_series":
        data["card_ids"] = [str(labels.resolve("card", c)) for c in data.pop("cards")]
    elif element.kind == "visualization":
        data["request_id"] = _optional(labels, "request", data.pop("request"))
    elif element.kind == "material_link":
        data["chunk_id"] = labels.resolve("chunk", data.pop("chunk"))
    return _ELEMENT_RECORD.validate_python(data)


def _condition(element: Element | None) -> str:
    """The text the learner sees for the task (D-B-149)."""
    if element is None:
        return ""
    text = getattr(element, "prompt", None) or getattr(element, "text", None)
    return str(text or "")


def _manifest_params(manifest: TurnManifestRow) -> dict[str, Any]:
    return {
        "manifest_id": manifest.manifest_id,
        "learner_id": manifest.learner_id,
        "session_id": manifest.session_id,
        "prompt_version": manifest.prompt_version,
        "doctrine_version": manifest.doctrine_version,
        "renderer_version": manifest.renderer_version,
        "role": manifest.role,
        "model": manifest.model,
        "effort": manifest.effort,
        "projected_seq": manifest.projected_seq,
        "overlay_seqs": manifest.overlay_seqs,
        "label_table": Jsonb(manifest.label_table),
        "digest_id": manifest.digest_id,
        "chunk_ids": manifest.chunk_ids,
        "similar_ids": manifest.similar_ids,
        "context_text": manifest.context_text,
        "degraded_mode": manifest.degraded_mode,
    }


__all__ = [
    "NewTurnTask",
    "TurnBatch",
    "TurnManifestRow",
    "commit_turn",
    "markup_record",
    "turn_batch",
]
