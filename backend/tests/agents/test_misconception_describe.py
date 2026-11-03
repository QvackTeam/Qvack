"""The misconception describer, WP16.2 (ТЗ Ф4; Т-§9.3, Т-§9.2; `T-AG2`): not confirmed — exit
without a model call; the input is all manifestations and no earlier wording (law 10); the event
`misconception.described` with a key from the source (law 5). D-B-175."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, cast
from uuid import UUID, uuid4

from pydantic import BaseModel

from quack.agents.misconception_describe import (
    NONE_LINE,
    DescriberInput,
    Manifestation,
    describe_misconception,
    render_manifestations,
)
from quack.agents.schemas import MisconceptionDescription
from quack.config import Settings
from quack.db import Db
from quack.events.records import TaskMarkupRecord, TestedLevelRecord
from quack.events.values import AnswerSpec, MathValue
from quack.llm.gateway import LLMGateway, LLMResult
from quack.practice.role_outputs import TaskCondition
from quack.practice.task_store import create_task
from quack.prompts.registry import PromptRegistry
from tests.db.fixtures import create_learner

SETTINGS = Settings()
DAY_MS = 86_400_000
AT_MS = 1_699_000_000_000  # 2023-11-03 UTC


@dataclass
class _Gateway:
    answer: MisconceptionDescription
    calls: list[dict[str, Any]] = field(default_factory=list)

    async def generate_structured(
        self,
        role: str,
        prompt_version: int,
        response_model: type[BaseModel],
        variables: dict[str, Any],
        learner_id: UUID,
        session_id: UUID | None,
        turn_id: UUID | None,
        idempotency_key: str,
        temperature: float = 0.0,
        **kwargs: Any,
    ) -> LLMResult[Any]:
        self.calls.append({"role": role, "variables": variables, "key": idempotency_key})
        return LLMResult(
            value=self.answer, from_cache=False, prompt_hash="h", model="m", usage=None
        )


def _facts(status: str, manifestations: list[Manifestation]) -> DescriberInput:
    return DescriberInput(
        misconception_id=uuid4(),
        status=status,
        skill_name="adding fractions",
        manifestations=manifestations,
    )


async def _task(db: Db, learner_id: UUID, text: str) -> UUID:
    task_id = uuid4()
    await create_task(
        db,
        learner_id=learner_id,
        task_id=task_id,
        family_id=uuid4(),
        source="generated",
        condition=TaskCondition(text=text, latex=None),
        markup=TaskMarkupRecord(
            tests=[TestedLevelRecord(skill_id=uuid4(), level=2)],
            method_named=False,
            answer=AnswerSpec(type="number", value=MathValue(latex="5/6", sympy="5/6")),
        ),
        verification="checked",
        actor="task_generator@1",
        idempotency_key=f"task:{task_id}",
    )
    return task_id


async def test_describer_exits_if_not_confirmed(pg_db: Db) -> None:
    """T-AG2: no misconception, `suspected` — no call, no event."""
    learner_id = await create_learner(pg_db)
    gateway = _Gateway(MisconceptionDescription(statement="s", triggers=[]))
    for facts in (None, _facts("suspected", [Manifestation("q", None, AT_MS)])):
        found = await describe_misconception(
            pg_db,
            cast(LLMGateway, gateway),
            SETTINGS,
            learner_id=learner_id,
            trigger_seq=7,
            facts=facts,
        )
        assert found is None
    assert gateway.calls == []


async def test_describer_writes_from_all_manifestations(pg_db: Db) -> None:
    """Т-§9.3: every manifestation in time order with its problem and date; the skill by name;
    no earlier statement; one event per trigger, a retry is the same event."""
    learner_id = await create_learner(pg_db)
    task_id = await _task(pg_db, learner_id, "Add 1/2 and 1/3")
    stranger_task = await _task(pg_db, await create_learner(pg_db), "Someone else's problem")
    facts = _facts(
        "watching",
        [
            Manifestation("the bottoms add up too", task_id, AT_MS + DAY_MS),
            Manifestation("1/2 + 1/3 = 2/5", None, AT_MS),
            Manifestation("same for 1/4 + 1/4", stranger_task, AT_MS + 2 * DAY_MS),
        ],
    )
    gateway = _Gateway(
        MisconceptionDescription(
            statement=" Adds denominators when adding fractions. ",
            triggers=["fractions with different denominators", " "],
        )
    )

    async def run(trigger_seq: int) -> Any:
        return await describe_misconception(
            pg_db,
            cast(LLMGateway, gateway),
            SETTINGS,
            learner_id=learner_id,
            trigger_seq=trigger_seq,
            facts=facts,
        )

    first = await run(40)
    variables = gateway.calls[0]["variables"]
    assert variables["skill"] == "adding fractions"
    assert variables["manifestations"].splitlines() == [
        '1. 2023-11-03, in conversation, no problem; the learner: "1/2 + 1/3 = 2/5"',
        '2. 2023-11-04, problem: Add 1/2 and 1/3; the learner: "the bottoms add up too"',
        '3. 2023-11-05, in conversation, no problem; the learner: "same for 1/4 + 1/4"',
    ]
    PromptRegistry().load("misconception_describer", 1).render(variables)
    assert first.type == "misconception.described"
    assert first.actor == "misconception_describer@1"
    assert first.causation_seq == 40
    assert first.idempotency_key == f"misconception.described:{facts.misconception_id}:40"
    assert first.payload == {
        "misconception_id": str(facts.misconception_id),
        "statement": "Adds denominators when adding fractions.",
        "triggers": ["fractions with different denominators"],
    }
    assert (await run(40)).seq == first.seq
    assert (await run(41)).seq != first.seq


def test_no_manifestations_is_named() -> None:
    assert render_manifestations([], {}) == NONE_LINE
