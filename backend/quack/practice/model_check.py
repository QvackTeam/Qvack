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

from quack.config import Settings
from quack.practice.check import HelpUsed, Verdict
from quack.practice.role_outputs import ModelVerdictOutput


@dataclass(frozen=True)
class LevelState:
    """State of one level the task tests (`skill`, `level` of its markup), read from memory:
    proven by a direct Т1 or Т2; the latest Т1 of this level by time is a failure
    [РЕШЕНИЕ Ф4 WP11.6]."""

    proven_by_direct: bool
    last_t1_failed: bool


def model_verdict(
    output: ModelVerdictOutput, *, answer_seq: int, part: str, help_used: HelpUsed | None = None
) -> Verdict:
    """`verdict.recorded` of a model verdict (Т-§6.8, WP11.4): class model, rubric items with
    quotes, confidence, a misconception label or hypothesis."""
    raise NotImplementedError


def needs_second_opinion(
    verdict: Verdict, levels: Sequence[LevelState], settings: Settings
) -> bool:
    """Т-§7.7: only a model verdict and only in doubt — confidence below
    `verdict_min_confidence`, or `incorrect` on a level proven by a direct Т1/Т2, or `correct`
    on a level whose latest Т1 failed."""
    raise NotImplementedError


def with_second_opinion(first: Verdict, second: ModelVerdictOutput) -> Verdict:
    """The first verdict with `secondOpinion {requested: true, agreed}` (Т-§7.7)."""
    raise NotImplementedError
