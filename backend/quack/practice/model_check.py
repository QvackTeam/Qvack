"""Model verdicts and the second opinion (Т-§6.8, Т-§7.7; ТЗ Ф4 WP11.6).

The body of the job `check.model` (rules — seam S6): `check_with_model` calls `verdict_proof`
or `verdict_free` with the condition, the rubric, the spec, the known misconceptions (labels
`M…`) and the answer; turns the output into a `Verdict`; asks `needs_second_opinion` with the
state of the tested levels (`quack.graph.read`, seam S4) and, if so, calls `second_opinion`;
`record_verdict` writes `verdict.recorded` under `verdict:{answer_seq}:{part}`. The tier (Т2
agreed, Т3 not) is set by code from `secondOpinion` (WP4.1, stream A), never here (law 4).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from quack.config import Settings
from quack.db.db import Db
from quack.events.event_types import AnswerSubmitted
from quack.llm.gateway import LLMGateway
from quack.practice.answer_spec import AnswerSpec, AnswerType
from quack.practice.check import HelpUsed, RubricItemResult, SecondOpinion, Verdict
from quack.practice.role_outputs import ModelVerdictOutput, SolutionSpace, TaskCondition


@dataclass(frozen=True)
class LevelState:
    """State of one level the task tests (`skill`, `level` of its markup), read from memory:
    proven by a direct Т1 or Т2; the latest Т1 of this level by time is a failure
    [РЕШЕНИЕ Ф4 WP11.6]."""

    proven_by_direct: bool
    last_t1_failed: bool


def model_verdict(
    output: ModelVerdictOutput,
    *,
    answer_seq: int,
    part: str,
    help_used: HelpUsed | None = None,
    known_misconceptions: Sequence[UUID] = (),
) -> Verdict:
    """`verdict.recorded` of a model verdict (Т-§6.8, WP11.4): class model, rubric items with
    quotes, confidence, a misconception id or hypothesis. `known_misconceptions` lists the ids
    behind the labels `M1`... in the order the prompt showed them; the event never carries a
    label (Т-§4.5, Q-A-2 п.1), an unknown label is dropped."""
    help_used = help_used or HelpUsed()
    misconception_id = _misconception_id(output.misconception, known_misconceptions)
    return Verdict(
        answer_seq=answer_seq,
        part=part,
        outcome=output.outcome,
        method="model",
        verification="model",
        confidence=output.confidence,
        help_step=help_used.hint_step,
        solution_shown=help_used.solution_requested,
        rubric=[
            RubricItemResult(item=i.item, status=i.status, quote=i.quote) for i in output.items
        ],
        misconception_id=misconception_id,
        misconception_hypothesis=None if misconception_id else output.misconception_hypothesis,
    )


def _misconception_id(label: str | None, known: Sequence[UUID]) -> UUID | None:
    if label is None:
        return None
    label = label.strip()
    if label.startswith("M") and label[1:].isdigit() and 1 <= int(label[1:]) <= len(known):
        return known[int(label[1:]) - 1]
    return None


def needs_second_opinion(
    verdict: Verdict, levels: Sequence[LevelState], settings: Settings
) -> bool:
    """Т-§7.7: only a model verdict and only in doubt — confidence below
    `verdict_min_confidence`, or `incorrect` on a level proven by a direct Т1/Т2, or `correct`
    on a level whose latest Т1 failed. `partial` contradicts neither (Т-§7.7, spike)."""
    if verdict.verification != "model":
        return False
    if verdict.confidence is not None and verdict.confidence < settings.verdict_min_confidence:
        return True
    if verdict.outcome == "incorrect":
        return any(level.proven_by_direct for level in levels)
    if verdict.outcome == "correct":
        return any(level.last_t1_failed for level in levels)
    return False


def with_second_opinion(first: Verdict, second: ModelVerdictOutput) -> Verdict:
    """The first verdict with `secondOpinion {requested: true, agreed}` (Т-§7.7): agreed —
    the same outcome."""
    agreed = second.outcome == first.outcome
    return first.model_copy(update={"second_opinion": SecondOpinion(requested=True, agreed=agreed)})


# --- the job body (WP11.6) ---


@dataclass(frozen=True)
class KnownMisconception:
    """A misconception of the tested skills shown to the model with a label `M…`."""

    misconception_id: UUID
    statement: str


def verdict_role(answer_type: AnswerType, *, failed: bool) -> str:
    """Т-§6.8, Т-§22.7: `proof` — `verdict_proof`; a short free answer, a drawing and a fast
    answer that did not check (`check.failed`) — `verdict_free`."""
    raise NotImplementedError


def verdict_inputs(
    condition: TaskCondition,
    spec: AnswerSpec,
    solution_space: SolutionSpace | None,
    answer: AnswerSubmitted,
    misconceptions: Sequence[KnownMisconception],
) -> dict[str, str]:
    """Input blocks of `verdict_*@1` and `second_opinion@1` (PROMPT_CONTRACTS.md): the rubric
    is the key steps of the solution space, else the key ideas of the spec (Т-§6.8)."""
    raise NotImplementedError


async def check_with_model(
    gateway: LLMGateway,
    settings: Settings,
    *,
    learner_id: UUID,
    session_id: UUID | None,
    condition: TaskCondition,
    spec: AnswerSpec,
    solution_space: SolutionSpace | None,
    answer: AnswerSubmitted,
    answer_seq: int,
    part: str,
    failed: bool,
    misconceptions: Sequence[KnownMisconception],
    levels: Sequence[LevelState],
    help_used: HelpUsed,
) -> Verdict:
    """One call of the verdict role per answer, a second opinion only in doubt (Т-§7.7)."""
    raise NotImplementedError


async def record_verdict(
    db: Db, verdict: Verdict, *, learner_id: UUID, session_id: UUID | None, domain_id: UUID | None
) -> None:
    """`verdict.recorded` under `verdict:{answer_seq}:{part}`: a repeat writes nothing new."""
    raise NotImplementedError
