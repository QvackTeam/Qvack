"""The misconception describer, WP16.2 (ТЗ Ф4; Т-§9.3, Т-§9.2; `T-AG2`). D-B-175.

- The job `misconception.describe` (WP7.1) reads the status first and ends without a call
  unless the misconception is confirmed: `confirmed`, `in_work` (confirmed and targeted) or
  `watching` (confirmed and resisting) — Т-§9.2.
- Input: the name of its skill and **all** manifestations — quote, the condition of the task,
  the date; no earlier wording (law 10).
- Output `statement`, `triggers` (`misconception_describer@1`); the event
  `misconception.described` with key `misconception.described:{misconception_id}:{trigger_seq}`
  (law 5: a retry of the job is the same event).

The facts come from `GraphReader.misconception_detail` of stream A (S4, its answer in #155);
`DescriberInput` is what this module needs of them.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from quack.agents.schemas import MisconceptionDescription
from quack.config import Settings
from quack.db.db import Db
from quack.events.event_types import MisconceptionDescribed
from quack.events.log import NewEvent, StoredEvent, append_events
from quack.llm.gateway import LLMGateway
from quack.practice.task_store import get_task

DESCRIBER_ROLE = "misconception_describer"
CONFIRMED_STATUSES = frozenset({"confirmed", "in_work", "watching"})
NONE_LINE = "(none)"


@dataclass(frozen=True)
class Manifestation:
    quote: str
    task_id: UUID | None
    at_ms: int


@dataclass(frozen=True)
class DescriberInput:
    misconception_id: UUID
    status: str
    skill_name: str
    manifestations: Sequence[Manifestation]


def describer_key(misconception_id: UUID, trigger_seq: int) -> str:
    return f"misconception.described:{misconception_id}:{trigger_seq}"


def _date(at_ms: int) -> str:
    return datetime.fromtimestamp(at_ms / 1000, UTC).strftime("%Y-%m-%d")


def render_manifestations(
    manifestations: Sequence[Manifestation], conditions: dict[UUID, str]
) -> str:
    """One numbered line per manifestation in time order: date, the problem, the quote."""
    lines: list[str] = []
    for n, item in enumerate(sorted(manifestations, key=lambda m: m.at_ms), start=1):
        condition = conditions.get(item.task_id) if item.task_id is not None else None
        problem = f"problem: {condition}" if condition else "in conversation, no problem"
        lines.append(f'{n}. {_date(item.at_ms)}, {problem}; the learner: "{item.quote}"')
    return "\n".join(lines) or NONE_LINE


async def _conditions(
    db: Db, learner_id: UUID, manifestations: Sequence[Manifestation]
) -> dict[UUID, str]:
    found: dict[UUID, str] = {}
    for task_id in dict.fromkeys(m.task_id for m in manifestations if m.task_id is not None):
        task = await get_task(db, learner_id=learner_id, task_id=task_id)
        if task is not None:
            found[task_id] = task.condition.text
    return found


async def describe_misconception(
    db: Db,
    gateway: LLMGateway,
    settings: Settings,
    *,
    learner_id: UUID,
    trigger_seq: int,
    facts: DescriberInput | None,
    domain_id: UUID | None = None,
) -> StoredEvent | None:
    """`T-AG2`: no misconception or not confirmed — `None` without a model call."""
    if facts is None or facts.status not in CONFIRMED_STATUSES:
        return None
    prompt = settings.llm_roles[DESCRIBER_ROLE].prompt
    if prompt is None:
        raise ValueError("role 'misconception_describer' has no prompt")
    conditions = await _conditions(db, learner_id, facts.manifestations)
    key = describer_key(facts.misconception_id, trigger_seq)
    result = await gateway.generate_structured(
        DESCRIBER_ROLE,
        int(prompt.rsplit("@", 1)[1]),
        MisconceptionDescription,
        {
            "skill": facts.skill_name,
            "manifestations": render_manifestations(facts.manifestations, conditions),
        },
        learner_id,
        None,
        None,
        key,
    )
    description = result.value
    (stored,) = await append_events(
        db,
        learner_id,
        [
            NewEvent(
                type="misconception.described",
                payload=MisconceptionDescribed(
                    misconception_id=facts.misconception_id,
                    statement=description.statement.strip(),
                    triggers=[t.strip() for t in description.triggers if t.strip()],
                ),
                actor=prompt,
                idempotency_key=key,
                domain_id=domain_id,
                causation_seq=trigger_seq,
            )
        ],
    )
    return stored
