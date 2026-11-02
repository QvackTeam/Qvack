"""Model verdicts and the second opinion (Т-§6.8, Т-§7.7; ТЗ Ф4 WP11.6), pure part.

The job `check.model` (WP7.1, rules — seam S6) calls `verdict_proof` / `verdict_free`, turns
the output into a `Verdict` here, asks `needs_second_opinion` with the state of the tested
levels (from `quack.graph.read`, seam S4) and, if so, calls `second_opinion` and records the
result with `with_second_opinion`. The tier (Т2 agreed, Т3 not) is set by code from
`secondOpinion` (WP4.1, stream A), never here (law 4).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from quack.config import Settings
from quack.practice.check import HelpUsed, RubricItemResult, SecondOpinion, Verdict
from quack.practice.role_outputs import ModelVerdictOutput


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
