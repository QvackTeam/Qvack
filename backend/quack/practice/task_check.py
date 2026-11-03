"""Check of a task before it is trusted, WP12.5 (ТЗ Ф4; `Т-§5.6`; `T-TK6`), the row «teacher on
the fly»: right after the turn (`task.check`), `task_checker` (Spark) solves the task blindly
and judges its markup; code compares its answer with the key by the same `check()` as the
learner's answers (Т-§6.1). The turn does not wait (`Т-§13.3`).

- key differs → `task.key_disputed` (verdicts already given go down to class model — the fold);
- key holds, markup differs → `task.markup_disputed` with the markup corrected by the checker
  (refold);
- both hold → `task.verified`.

A key code cannot decide (a slow type, compute down, an unparsed answer) is not disputed: only
the markup is judged. D-B-167.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal
from uuid import UUID

from quack.compute_client.client import ComputeClient
from quack.config import Settings
from quack.db import Db
from quack.events.event_types import TaskCreated, TaskKeyDisputed, TaskMarkupDisputed, TaskVerified
from quack.events.log import NewEvent, StoredEvent, append_events
from quack.events.records import TaskMarkupRecord, TestedLevelRecord
from quack.events.values import LearnerAnswer, Verdict
from quack.llm.gateway import LLMGateway
from quack.practice.check import check
from quack.practice.role_outputs import TaskCheckOutput
from quack.practice.task_store import TaskDocument, get_task

CHECKER_ROLE = "task_checker"
NONE_LINE = "(none)"

type CheckEvent = Literal["task.verified", "task.key_disputed", "task.markup_disputed"]

_SELECT_CREATED = (
    "SELECT payload FROM core.events WHERE learner_id = %(learner_id)s AND seq = %(seq)s "
    "AND type = 'task.created'"
)


def check_key(task_id: UUID) -> str:
    """One check per task: a retry of the job writes the same event (law 5)."""
    return f"task_check:{task_id}"


def checker_variables(
    doc: TaskDocument,
    markup: TaskMarkupRecord,
    skill_names: Mapping[UUID, str],
    source: TaskDocument | None = None,
) -> dict[str, str]:
    """The four input blocks of `task_checker@1`; the key is not given (blind solving)."""
    options = doc.answer_spec.options or []
    tests = [
        f"{i}. {_skill(t, skill_names)} — level {t.level}" for i, t in enumerate(markup.tests, 1)
    ]
    claimed = [
        f"method named: {'yes' if markup.method_named else 'no'}",
        "tested skills and levels:",
        *tests,
    ]
    return {
        "problem": _problem(doc),
        "options": "\n".join(f"{o.option_id}. {o.text}" for o in options) or NONE_LINE,
        "claimed_markup": "\n".join(claimed),
        "source_problem": _problem(source) if source is not None else NONE_LINE,
    }


def _skill(test: TestedLevelRecord, names: Mapping[UUID, str]) -> str:
    if test.skill_id is not None:
        return names.get(test.skill_id, "unnamed skill")
    return test.new_skill.name if test.new_skill else "unnamed skill"


def _problem(doc: TaskDocument) -> str:
    return doc.condition.text + (f"\n{doc.condition.latex}" if doc.condition.latex else "")


def checker_answer(output: TaskCheckOutput, doc: TaskDocument) -> LearnerAnswer:
    """The checker's answer in the type of the spec, as a learner's answer."""
    math = output.answer_math
    return LearnerAnswer(
        kind=doc.answer_spec.type,
        value=output.answer_text,
        latex=math.latex if math else None,
        sympy=math.sympy if math else None,
    )


def corrected_markup(output: TaskCheckOutput, markup: TaskMarkupRecord) -> TaskMarkupRecord | None:
    """The markup as the checker sees it, or `None` when it agrees: `method_named` by the
    checker, unfit levels dropped, `variant_of` dropped when it is no variant. All levels unfit
    leaves no tests to keep — the dispute has no correction (`None` with a dispute)."""
    fits = list(output.levels_fit) + [True] * (len(markup.tests) - len(output.levels_fit))
    tests = [t for t, fit in zip(markup.tests, fits, strict=False) if fit]
    not_variant = markup.variant_of is not None and output.is_variant is False
    same = output.method_named == markup.method_named and len(tests) == len(markup.tests)
    if same and not not_variant:
        return None
    return markup.model_copy(
        update={
            "method_named": output.method_named,
            "tests": tests or markup.tests,
            "variant_of": None if not_variant else markup.variant_of,
        }
    )


def markup_disputed(output: TaskCheckOutput, markup: TaskMarkupRecord) -> bool:
    fits = list(output.levels_fit)[: len(markup.tests)]
    return (
        output.method_named != markup.method_named
        or not all(fits)
        or (markup.variant_of is not None and output.is_variant is False)
    )


async def check_teacher_task(
    db: Db,
    gateway: LLMGateway,
    settings: Settings,
    *,
    learner_id: UUID,
    task_id: UUID,
    skill_names: Mapping[UUID, str],
    compute: ComputeClient | None = None,
    causation_seq: int | None = None,
) -> StoredEvent | None:
    """`task.check` of one task of the turn; `None` for a task that is not the learner's."""
    doc = await get_task(db, learner_id=learner_id, task_id=task_id)
    if doc is None:
        return None
    row = await db.fetch_one(_SELECT_CREATED, {"learner_id": learner_id, "seq": doc.created_seq})
    if row is None:
        raise LookupError(f"task {task_id} has no task.created at seq {doc.created_seq}")
    markup = TaskCreated.model_validate(row["payload"]).markup
    source = (
        await get_task(db, learner_id=learner_id, task_id=markup.variant_of)
        if markup.variant_of
        else None
    )
    prompt = settings.llm_roles[CHECKER_ROLE].prompt
    if prompt is None:
        raise ValueError(f"role {CHECKER_ROLE!r} has no prompt")
    result = await gateway.generate_structured(
        CHECKER_ROLE,
        int(prompt.rsplit("@", 1)[1]),
        TaskCheckOutput,
        checker_variables(doc, markup, skill_names, source),
        learner_id,
        None,
        None,
        f"{check_key(task_id)}:{prompt}",
    )
    output = result.value
    verdict = await check(
        checker_answer(output, doc),
        doc.answer_spec,
        answer_seq=0,
        part="main",
        settings=settings,
        compute=compute,
        timeout_ms=settings.symbolic_background_timeout_ms,
    )
    key_wrong = isinstance(verdict, Verdict) and verdict.outcome == "incorrect"
    corrected = corrected_markup(output, markup) if markup_disputed(output, markup) else None
    if key_wrong:
        kind: CheckEvent = "task.key_disputed"
        payload = TaskKeyDisputed(task_id=task_id, corrected_markup=corrected)
    elif markup_disputed(output, markup):
        kind = "task.markup_disputed"
        payload = TaskMarkupDisputed(task_id=task_id, corrected_markup=corrected)
    else:
        kind = "task.verified"
        payload = TaskVerified(task_id=task_id)
    (stored,) = await append_events(
        db,
        learner_id,
        [
            NewEvent(
                type=kind,
                payload=payload,
                actor=prompt,
                idempotency_key=check_key(task_id),
                domain_id=doc.domain_id,
                causation_seq=causation_seq,
            )
        ],
    )
    return stored
